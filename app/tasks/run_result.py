# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Report a run's structured result from its logs to a per-task recorder.

A payload emits one machine-readable marker line on its stdout when it produces
a result; at terminal status the tasks service reassembles that line from the
run's persisted logs and hands the decoded payload to a per-task recorder the
owning plugin declared. The recorder path is resolved lazily via
:func:`app.tasks.hook_resolver.resolve_hook`, mirroring
:mod:`app.tasks.alert_hooks`, so this channel stays free of any static
``app.sep`` import. The marker payload is passed through as a plain ``dict`` —
the tasks service never learns a plugin's field names; the recorder validates
the payload into its own model.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.crud import TaskHistoryManager
from app.tasks.db import get_async_session_maker
from app.tasks.hook_resolver import resolve_hook
from app.tasks.logs.log_reader import iter_task_history_logs
from app.tasks.models import TaskHistory, TaskLogType

logger = logging.getLogger(__name__)

#: Fixed sentinel that prefixes the single-line JSON result payload a payload
#: emits on stdout. The trailing space separates it from the JSON body.
RUN_RESULT_MARKER = "@@SEP-RUN-RESULT@@ "

#: An ``async`` callable a plugin declares on ``Task.run_result_recorder`` to
#: record a terminal run's parsed result (``None`` when no marker was emitted).
RunResultRecorder = Callable[
    [AsyncSession, TaskHistory, dict[str, Any] | None], Awaitable[None]
]


def _collect_marker(line: str, markers: list[dict[str, Any]]) -> None:
    """Append the decoded payload of a marker ``line`` to ``markers``.

    Do nothing when the line carries no sentinel; skip (logged) a sentinel whose
    trailing payload is not a JSON object.

    :param line: A single complete stdout line to scan for the sentinel.
    :param markers: The accumulator to append a decoded payload to.
    """
    index = line.find(RUN_RESULT_MARKER)
    if index == -1:
        return
    payload = line[index + len(RUN_RESULT_MARKER) :]
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("Ignoring unparseable run-result marker payload: %r", payload)
        return
    if not isinstance(decoded, dict):
        logger.warning("Ignoring non-object run-result marker payload: %r", payload)
        return
    markers.append(decoded)


async def parse_run_result(
    session: AsyncSession, task_history: TaskHistory
) -> dict[str, Any] | None:
    """Decode the run-result marker from a run's stdout logs.

    Stream the run's logs, reassembling complete stdout lines across the
    chunk boundaries the log store splits them on (a marker line may straddle
    two chunks), and scan each line for the sentinel. Return the last decoded
    payload, or ``None`` when no valid marker is present.

    :param session: The async session to read the persisted logs with.
    :param task_history: The terminal history whose logs to scan; must have
        ``execution_request`` loaded.
    :return: The decoded marker payload, or ``None`` when none is found.
    """
    markers: list[dict[str, Any]] = []
    buffer = ""
    current_step: str | None = None
    async for log in iter_task_history_logs(session, task_history):
        if log.type != TaskLogType.STDOUT:
            continue
        if log.step != current_step:
            _collect_marker(buffer, markers)
            buffer = ""
            current_step = log.step
        if log.msg is None:
            continue
        buffer += log.msg
        *complete, buffer = buffer.split("\n")
        for line in complete:
            _collect_marker(line, markers)
    _collect_marker(buffer, markers)
    if not markers:
        return None
    if len(markers) > 1:
        logger.warning(
            "Found %d run-result markers in task history %s; using the last.",
            len(markers),
            task_history.id,
        )
    return markers[-1]


async def maybe_record_run(task_history_id: int) -> None:
    """Resolve and invoke the task's run-result recorder at terminal status.

    Best-effort: no-op when the history is missing, not terminal, or declares no
    recorder; and any failure (unresolvable path, parse error, recorder raising,
    DB error) is logged and swallowed so recording can never fail the
    task-history sync.

    :param task_history_id: The id of the just-synced ``TaskHistory``.
    """
    try:
        session_maker = get_async_session_maker()
        async with session_maker() as session:
            history = await TaskHistoryManager.first(
                session,
                select_related=[TaskHistory.task],
                id=task_history_id,
            )
            if history is None or not history.status.is_terminal():
                return
            recorder_path = history.task.run_result_recorder
            if not recorder_path:
                return
            recorder: RunResultRecorder = resolve_hook(recorder_path)
            await session.refresh(history, ["execution_request"])
            result = await parse_run_result(session, history)
            await recorder(session, history, result)
    except Exception:
        logger.exception(
            "Run-result recorder failed for task history %s.", task_history_id
        )
