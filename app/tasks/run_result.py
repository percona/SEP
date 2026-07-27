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

"""Report a run's structured result from its output files to a per-task recorder.

A payload writes a machine-readable JSON result to a reserved filename in its
working directory when it produces one; at terminal status the tasks service
reads that file back through the executor and hands the decoded payload to a
per-task recorder the owning plugin declared. The recorder path is resolved
lazily via :func:`app.tasks.hook_resolver.resolve_hook`, mirroring
:mod:`app.tasks.alert_hooks`, so this channel stays free of any static
``app.sep`` import. The result is passed through as a plain ``dict`` — the tasks
service never learns a plugin's field names; the recorder validates the payload
into its own model.
"""

import json
import logging
import posixpath
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.crud import TaskHistoryManager
from app.tasks.db import get_async_session_maker
from app.tasks.execution.exceptions import TaskDataNotFoundInExecutorError
from app.tasks.execution.models import BaseExecutor
from app.tasks.hook_resolver import resolve_hook
from app.tasks.models import TaskHistory

logger = logging.getLogger(__name__)

#: Fixed name of the file a payload writes its result to, relative to the run's
#: working directory — which the job spec pins to the task's output-files
#: directory, so this resolves under :attr:`Task.output_files_path` on read.
RUN_RESULT_FILENAME = "sep-run-result.json"

#: Upper bound on a result file's size. A run result is a handful of scalar
#: fields; anything larger is a payload bug and is discarded unread.
RUN_RESULT_MAX_BYTES = 16_384

#: An ``async`` callable a plugin declares on ``Task.run_result_recorder`` to
#: record a terminal run's result (``None`` when the run produced no result).
RunResultRecorder = Callable[
    [AsyncSession, TaskHistory, dict[str, Any] | None], Awaitable[None]
]


async def _read_run_result(
    executor: BaseExecutor, history: TaskHistory
) -> dict[str, Any] | None:
    """Read a terminal run's result file through the executor.

    The read opts out of anonymization: this content is SEP's own protocol, not
    output served to a user, and redaction would corrupt the very fields the
    recorder consumes. Every shape of "this run produced no result" — no file,
    an empty one, an executor without file support, an allocation already gone —
    maps to ``None``; anything else propagates to the caller's failure logging.

    :param executor: The executor that ran the task, used to read its files.
    :param history: The terminal history to read the result of; must have both
        ``task`` and ``execution_request`` loaded.
    :return: The decoded result object, or ``None`` when there is none to read.
    """
    task = history.task
    if task is None or not task.output_files_path:
        return None
    path = posixpath.join(task.output_files_path, RUN_RESULT_FILENAME)
    buffer = bytearray()
    try:
        async for chunk in executor.stream_file(history, path, anonymize=False):
            buffer.extend(chunk)
            if len(buffer) > RUN_RESULT_MAX_BYTES:
                logger.warning(
                    "Run-result file for task history %s exceeds %d bytes; ignoring.",
                    history.id,
                    RUN_RESULT_MAX_BYTES,
                )
                return None
        result = json.loads(buffer.decode())
    except (
        NotImplementedError,
        TaskDataNotFoundInExecutorError,
        aiohttp.ClientError,
        ValueError,
        UnicodeDecodeError,
    ):
        logger.debug(
            "No readable run result for task history %s.", history.id, exc_info=True
        )
        return None
    if not isinstance(result, dict):
        logger.warning("Ignoring non-object run result: %r", result)
        return None
    return result


async def maybe_record_run(task_history_id: int, executor: BaseExecutor) -> None:
    """Resolve and invoke the task's run-result recorder at terminal status.

    Best-effort: no-op when the history is missing, not terminal, or declares no
    recorder; and any failure (unresolvable path, unexpected executor error,
    recorder raising, DB error) is logged and swallowed so recording can never
    fail the task-history sync.

    :param task_history_id: The id of the just-synced ``TaskHistory``.
    :param executor: The executor that ran the task, used to read its result.
    """
    recorder_path: str | None = None
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
            result = await _read_run_result(executor, history)
            await recorder(session, history, result)
    except Exception:
        logger.exception(
            "Run-result recorder %r failed for task history %s.",
            recorder_path,
            task_history_id,
        )
