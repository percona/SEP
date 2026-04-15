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

"""Define tests for ``app.tasks.logs.log_reader``."""

import base64
import gzip
import json
import logging

import pytest
from sqlalchemy.orm import undefer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.crud import TaskHistoryManager
from app.tasks.logs.log_reader import (
    decompress_legacy_logs,
    iter_task_history_logs,
)
from app.tasks.logs.log_writer import TaskHistoryLogWriter
from app.tasks.models import TaskHistory, TaskLogType


async def _collect(agen):
    """Materialize an async generator into a list."""
    return [item async for item in agen]


async def _reload(session: AsyncSession, history: TaskHistory) -> TaskHistory:
    """Reload ``history`` with ``execution_request`` undeferred."""
    return await TaskHistoryManager.get_or_404(
        session,
        query_options=[undefer(TaskHistory.execution_request)],
        id=history.id,
    )


@pytest.mark.asyncio
async def test_iter_task_history_logs_reads_chunks(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert the chunk path yields chunk rows in order."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk-one",
        force_flush=True,
        producer_offset_after=9,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk-two",
        force_flush=True,
        producer_offset_after=18,
    )

    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history))
    assert [log.msg for log in logs] == ["chunk-one", "chunk-two"]
    assert [log.type for log in logs] == [TaskLogType.STDOUT, TaskLogType.STDOUT]


@pytest.mark.asyncio
async def test_iter_task_history_logs_source_filter(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``source`` filters the chunk stream."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"run-out",
        force_flush=True,
        producer_offset_after=7,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="prepare",
        stream=TaskLogType.STDOUT,
        new_bytes=b"prep-out",
        force_flush=True,
        producer_offset_after=8,
    )

    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history, source="run-script"))
    assert [log.step for log in logs] == ["run-script"]
    assert [log.msg for log in logs] == ["run-out"]


@pytest.mark.asyncio
async def test_iter_task_history_logs_start_offset_trims_chunk(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert the first partial chunk is trimmed to start at the offset."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"abcdefgh",
        force_flush=True,
        producer_offset_after=8,
    )

    history = await _reload(session, history)
    logs = await _collect(
        iter_task_history_logs(
            session,
            history,
            start_offsets={"run-script": {TaskLogType.STDOUT: 3}},
        )
    )
    assert [log.msg for log in logs] == ["defgh"]
    assert [log.offset for log in logs] == [8]


@pytest.mark.asyncio
async def test_iter_task_history_logs_start_offset_skips_fully_covered(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert chunks entirely below the start offset are skipped."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"first",
        force_flush=True,
        producer_offset_after=5,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"second",
        force_flush=True,
        producer_offset_after=11,
    )

    history = await _reload(session, history)
    logs = await _collect(
        iter_task_history_logs(
            session,
            history,
            start_offsets={"run-script": {TaskLogType.STDOUT: 5}},
        )
    )
    assert [log.msg for log in logs] == ["second"]


@pytest.mark.asyncio
async def test_iter_task_history_logs_falls_back_to_legacy_blob(
    session: AsyncSession,
    created_task_with_history: TaskHistory,
):
    """Assert the legacy blob is read when no chunks exist and a warning fires."""
    history = created_task_with_history
    legacy = {
        "run-script": {
            TaskLogType.STDOUT.value: "legacy stdout",
            TaskLogType.STDERR.value: "legacy stderr",
        }
    }
    encoded = base64.b64encode(gzip.compress(json.dumps(legacy).encode())).decode()
    history.execution_request.tracking["task_logs"] = encoded
    saved = await TaskHistoryManager.save(
        session, history, flag_modified_fields=["execution_request"]
    )

    history = await _reload(session, saved)
    reader_logger = logging.getLogger("app.tasks.logs.log_reader")
    captured = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record)

    handler = _Capture(level=logging.WARNING)
    reader_logger.addHandler(handler)
    try:
        logs = await _collect(iter_task_history_logs(session, history))
    finally:
        reader_logger.removeHandler(handler)

    warnings = [
        record
        for record in captured
        if record.getMessage() == "taskhistory_log dual-read fallback used"
    ]
    assert warnings
    assert warnings[0].event == "taskhistory_log_fallback"
    assert warnings[0].task_history_id == history.id
    messages = [log.msg for log in logs]
    assert "legacy stdout" in messages
    assert "legacy stderr" in messages


@pytest.mark.asyncio
async def test_iter_task_history_logs_empty_history_yields_nothing(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert an empty history without legacy content yields nothing."""
    history = created_task_with_history
    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history))
    assert logs == []


def test_decompress_legacy_logs_handles_both_shapes():
    """Assert both base64+gzip strings and plain dicts decode the same way."""
    payload = {"run-script": {"stdout": "text", "stdout_last_offset": 4}}
    encoded = base64.b64encode(gzip.compress(json.dumps(payload).encode())).decode()

    dict_history = TaskHistory.model_construct(
        execution_request=TaskHistory.model_fields["execution_request"].annotation(
            task="t", target="n", tracking={"task_logs": payload}
        )
    )
    str_history = TaskHistory.model_construct(
        execution_request=TaskHistory.model_fields["execution_request"].annotation(
            task="t", target="n", tracking={"task_logs": encoded}
        )
    )

    assert decompress_legacy_logs(dict_history) == payload
    assert decompress_legacy_logs(str_history) == payload
