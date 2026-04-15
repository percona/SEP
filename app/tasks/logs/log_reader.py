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

"""Define the task history log reader with a dual-read legacy fallback."""

import base64
import gzip
import json
import logging
from collections import defaultdict
from collections.abc import AsyncGenerator, Generator
from itertools import product

from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.crud import TaskHistoryLogManager
from app.tasks.models import (
    TaskHistory,
    TaskLog,
    TaskLogType,
)

logger = logging.getLogger(__name__)


def decompress_legacy_logs(task_history: TaskHistory) -> dict:
    """Return the decompressed legacy ``tracking["task_logs"]`` payload.

    Handles both historical encodings: the base64+gzip string produced by old
    Nomad syncs and the plain dict stored by some early Celery paths. Returns
    an empty dict when no legacy content exists.

    :param task_history: The task history whose legacy logs should be
        decompressed.
    :type task_history: TaskHistory
    :return: The legacy ``{step: {log_type: text, f"{log_type}_last_offset": int}}``
        dict, or an empty dict when no legacy content exists.
    :rtype: dict
    """
    tracking = task_history.execution_request.tracking or {}
    logs = tracking.get("task_logs") or {}
    if isinstance(logs, str):
        return json.loads(gzip.decompress(base64.b64decode(logs)))
    return logs


async def iter_task_history_logs(
    session: AsyncSession,
    task_history: TaskHistory,
    start_offsets: dict[str, dict[str, int]] | None = None,
    *,
    source: str | None = None,
) -> AsyncGenerator[TaskLog, None]:
    """Yield ``TaskLog`` records for a finished task history.

    When the chunk store has any row for ``task_history``, chunks are streamed
    from it in ``(source, stream, start_offset)`` order. Otherwise, a
    structured warning is logged and the legacy ``tracking["task_logs"]`` blob
    is decoded and yielded — this is the dual-read fallback used while
    pre-migration records are still in the database.

    :param session: The SQLAlchemy asynchronous session. Must have
        ``execution_request`` undeferred when the fallback path might run.
    :type session: AsyncSession
    :param task_history: The task history to read logs for. Must already have
        ``execution_request`` loaded.
    :type task_history: TaskHistory
    :param start_offsets: Optional per-step/per-stream start offsets. Chunks or
        bytes below the offset are skipped; the first partial chunk is trimmed
        so callers resume exactly where they left off.
    :type start_offsets: dict[str, dict[str, int]] | None
    :param source: Optional step filter. When set, only logs for the matching
        source are yielded.
    :type source: str | None
    :return: An async generator yielding ``TaskLog`` records in
        ``(source, stream, offset)`` order.
    :rtype: AsyncGenerator[TaskLog, None]
    """
    offsets = defaultdict(dict, start_offsets or {})
    has_chunks = await TaskHistoryLogManager.exists_for_task(session, task_history.id)
    if has_chunks:
        async for chunk in TaskHistoryLogManager.iter_chunks(
            session, task_history.id, source=source
        ):
            start_offset = offsets[chunk.source].get(chunk.stream, 0)
            if chunk.end_offset <= start_offset:
                continue
            if chunk.start_offset >= start_offset:
                yield TaskLog(
                    step=chunk.source,
                    type=chunk.stream,
                    msg=chunk.content,
                    offset=chunk.end_offset,
                )
                continue
            trim = start_offset - chunk.start_offset
            yield TaskLog(
                step=chunk.source,
                type=chunk.stream,
                msg=chunk.content[trim:],
                offset=chunk.end_offset,
            )
        return

    logger.warning(
        "taskhistory_log dual-read fallback used",
        extra={
            "event": "taskhistory_log_fallback",
            "task_history_id": task_history.id,
        },
    )
    for log in _iter_legacy_blob(task_history, offsets, source=source):
        yield log


def _iter_legacy_blob(
    task_history: TaskHistory,
    offsets: defaultdict[str, dict[str, int]],
    *,
    source: str | None,
    chunk_size: int = 65536,
) -> Generator[TaskLog, None, None]:
    """Yield ``TaskLog`` records from the legacy ``tracking["task_logs"]`` blob.

    Mirrors the behavior of the removed ``TaskHistory.iter_logs`` method so the
    fallback path keeps bit-for-bit compatibility with pre-migration records.
    """
    task_logs = decompress_legacy_logs(task_history)
    if source is not None:
        task_logs = {source: task_logs.get(source, {})}
    for (cur_step, log), log_type in product(task_logs.items(), TaskLogType):
        msg = log.get(log_type) or log.get(log_type.value) or ""
        start = offsets[cur_step].get(log_type, 0)
        for chunk_start in range(start, len(msg), chunk_size):
            chunk_end = chunk_start + chunk_size
            yield TaskLog(
                step=cur_step,
                type=log_type,
                msg=msg[chunk_start:chunk_end],
                offset=chunk_end,
            )
