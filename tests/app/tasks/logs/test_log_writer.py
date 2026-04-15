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

"""Define tests for ``app.tasks.logs.log_writer``."""

from datetime import timedelta

import pytest
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.utils.date_time import utc_now
from app.tasks.crud import TaskHistoryLogStateManager
from app.tasks.logs.log_writer import (
    backfill_legacy_logs,
    CHUNK_BYTES,
    LogWriterConflictError,
    MAX_AGE_SEC,
    MIN_FLUSH,
    TaskHistoryLogWriter,
)
from app.tasks.models import (
    TaskHistory,
    TaskHistoryLog,
    TaskLogType,
)

EXPECTED_HELLOWORLD_LEN = 10
EXPECTED_LEGACY_STDOUT_OFFSET = 42
EXPECTED_LEGACY_STDERR_OFFSET = 5
EXPECTED_PRE_EXISTING_STDOUT_OFFSET = 12
EXPECTED_PRE_EXISTING_STDERR_OFFSET = 13
EXPECTED_MULTI_STREAM_ROW_COUNT = 3
ALLOC_B_PRODUCER_OFFSET = 1_000


@pytest.mark.asyncio
async def test_append_creates_state_row_when_below_min_flush(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert short bytes stay in staging and create the state row."""
    history = created_task_with_history
    payload = b"hello"

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=payload,
        producer_offset_after=len(payload),
    )

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.staging == payload
    assert state.persisted_offset == 0
    assert state.producer_offset == len(payload)
    assert state.version == 1

    chunks = (
        await session.exec(
            select(TaskHistoryLog).where(
                col(TaskHistoryLog.task_history_id) == history.id
            )
        )
    ).all()
    assert chunks == []


@pytest.mark.asyncio
async def test_append_flushes_full_chunk(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``CHUNK_BYTES`` worth of bytes are persisted as one chunk row."""
    history = created_task_with_history
    payload = b"a" * (CHUNK_BYTES + 100)

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=payload,
        producer_offset_after=len(payload),
    )

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.persisted_offset == CHUNK_BYTES
    assert state.staging == b"a" * 100
    assert state.producer_offset == len(payload)

    chunks = (
        await session.exec(
            select(TaskHistoryLog).where(
                col(TaskHistoryLog.task_history_id) == history.id
            )
        )
    ).all()
    assert len(chunks) == 1
    assert chunks[0].start_offset == 0
    assert chunks[0].end_offset == CHUNK_BYTES
    assert chunks[0].content == "a" * CHUNK_BYTES


@pytest.mark.asyncio
async def test_append_force_flush_drains_staging(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``force_flush=True`` drains staging even when below ``MIN_FLUSH``."""
    history = created_task_with_history
    payload = b"short content"

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDERR,
        new_bytes=payload,
        force_flush=True,
        producer_offset_after=len(payload),
    )

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDERR
    )
    assert state is not None
    assert state.staging == b""
    assert state.persisted_offset == len(payload)

    chunks = (
        await session.exec(
            select(TaskHistoryLog).where(
                col(TaskHistoryLog.task_history_id) == history.id
            )
        )
    ).all()
    assert len(chunks) == 1
    assert chunks[0].content == payload.decode("utf-8")


@pytest.mark.asyncio
async def test_append_force_flush_empty_staging_is_noop(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``force_flush=True`` with no pending bytes inserts no chunks."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"",
        force_flush=True,
        producer_offset_after=0,
    )
    chunks = (
        await session.exec(
            select(TaskHistoryLog).where(
                col(TaskHistoryLog.task_history_id) == history.id
            )
        )
    ).all()
    assert chunks == []


@pytest.mark.asyncio
async def test_append_accumulates_below_min_flush(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert successive small appends accumulate into staging only."""
    history = created_task_with_history
    chunk_size = 1024
    total_calls = 5
    total_bytes = chunk_size * total_calls
    for idx in range(total_calls):
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            new_bytes=b"x" * chunk_size,
            producer_offset_after=(idx + 1) * chunk_size,
        )

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.staging == b"x" * total_bytes
    assert state.persisted_offset == 0
    chunks = (
        await session.exec(
            select(TaskHistoryLog).where(
                col(TaskHistoryLog.task_history_id) == history.id
            )
        )
    ).all()
    assert chunks == []


@pytest.mark.asyncio
async def test_append_max_age_flushes_remainder(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``staging_updated_at`` age above ``MAX_AGE_SEC`` flushes remainder."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"hello",
        producer_offset_after=5,
    )

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    state.staging_updated_at = utc_now() - timedelta(seconds=MAX_AGE_SEC + 10)
    session.add(state)
    await session.commit()

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"world",
        producer_offset_after=10,
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state.staging == b""
    assert state.persisted_offset == EXPECTED_HELLOWORLD_LEN
    chunks = (
        await session.exec(
            select(TaskHistoryLog)
            .where(col(TaskHistoryLog.task_history_id) == history.id)
            .order_by(col(TaskHistoryLog.start_offset))
        )
    ).all()
    assert len(chunks) == 1
    assert chunks[0].content == "helloworld"


@pytest.mark.asyncio
async def test_append_min_flush_triggers_remainder(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert staging at or above ``MIN_FLUSH`` triggers a remainder flush."""
    history = created_task_with_history
    payload = b"b" * MIN_FLUSH
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=payload,
        producer_offset_after=len(payload),
    )
    chunks = (
        await session.exec(
            select(TaskHistoryLog).where(
                col(TaskHistoryLog.task_history_id) == history.id
            )
        )
    ).all()
    assert len(chunks) == 1
    assert chunks[0].end_offset == MIN_FLUSH


@pytest.mark.asyncio
async def test_append_version_conflict_exhausts_retries(
    session: AsyncSession,
    created_task_with_history: TaskHistory,
    monkeypatch,
):
    """Assert a persistent version conflict raises ``LogWriterConflictError``."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"hello",
        producer_offset_after=5,
    )

    async def _always_conflict(**kwargs):
        return False

    monkeypatch.setattr(
        TaskHistoryLogWriter, "_persist_state", staticmethod(_always_conflict)
    )

    with pytest.raises(LogWriterConflictError):
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            new_bytes=b"world",
            producer_offset_after=10,
        )


@pytest.mark.asyncio
async def test_append_producer_offset_after_skips_persisted(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert overlapping new bytes are skipped based on ``producer_offset``."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"hello",
        force_flush=True,
        producer_offset_after=5,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"helloworld",
        force_flush=True,
        producer_offset_after=10,
    )

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state.persisted_offset == EXPECTED_HELLOWORLD_LEN
    assert state.producer_offset == EXPECTED_HELLOWORLD_LEN
    chunks = (
        await session.exec(
            select(TaskHistoryLog)
            .where(col(TaskHistoryLog.task_history_id) == history.id)
            .order_by(col(TaskHistoryLog.start_offset))
        )
    ).all()
    assert [chunk.content for chunk in chunks] == ["hello", "world"]


@pytest.mark.asyncio
async def test_append_multi_source_and_stream_independent(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert state rows for different ``(source, stream)`` tuples are independent."""
    history = created_task_with_history
    tuples = [
        ("run-script", TaskLogType.STDOUT, b"run-out"),
        ("run-script", TaskLogType.STDERR, b"run-err"),
        ("prepare", TaskLogType.STDOUT, b"prepare-out"),
    ]
    for source, stream, payload in tuples:
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source=source,
            stream=stream,
            new_bytes=payload,
            force_flush=True,
            producer_offset_after=len(payload),
        )
    rows = await TaskHistoryLogStateManager.list_for_task(session, history.id)
    assert len(rows) == EXPECTED_MULTI_STREAM_ROW_COUNT
    by_key = {(row.source, row.stream): row for row in rows}
    for source, stream, payload in tuples:
        row = by_key[(source, stream)]
        assert row.persisted_offset == len(payload)


@pytest.mark.asyncio
async def test_reset_producer_offsets_clears_db_and_allows_realloc_writes(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert producer_offset reset persists to the DB so alloc-switched bytes land.

    Regression test for SEP-817: the in-memory ``initial_offsets`` reset on
    Nomad follow-up allocation switch was not enough — the writer re-reads
    the state row from the DB on every ``append`` and would otherwise drop
    the new allocation's bytes via ``_effective_new_bytes``'s skip logic.
    """
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"alloc-a content",
        force_flush=True,
        producer_offset_after=50_000,
    )

    await TaskHistoryLogStateManager.reset_producer_offsets(session, history.id)
    await session.commit()

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.producer_offset == 0
    persisted_after_alloc_a = state.persisted_offset

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"alloc-b content",
        force_flush=True,
        producer_offset_after=ALLOC_B_PRODUCER_OFFSET,
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.producer_offset == ALLOC_B_PRODUCER_OFFSET
    assert state.persisted_offset == persisted_after_alloc_a + len(b"alloc-b content")
    chunks = (
        await session.exec(
            select(TaskHistoryLog)
            .where(col(TaskHistoryLog.task_history_id) == history.id)
            .order_by(col(TaskHistoryLog.start_offset))
        )
    ).all()
    assert [chunk.content for chunk in chunks] == ["alloc-a content", "alloc-b content"]


@pytest.mark.asyncio
async def test_backfill_legacy_logs_empty_is_noop(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``backfill_legacy_logs`` is a no-op for an empty dict."""
    history = created_task_with_history
    await backfill_legacy_logs(session, history.id, {})
    rows = await TaskHistoryLogStateManager.list_for_task(session, history.id)
    assert rows == []


@pytest.mark.asyncio
async def test_backfill_legacy_logs_migrates_streams(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``backfill_legacy_logs`` seeds chunks and state rows per stream."""
    history = created_task_with_history
    legacy = {
        "run-script": {
            TaskLogType.STDOUT: "hello",
            f"{TaskLogType.STDOUT.value}_last_offset": 42,
            TaskLogType.STDERR: "err",
            f"{TaskLogType.STDERR.value}_last_offset": 5,
        }
    }
    await backfill_legacy_logs(session, history.id, legacy)
    rows = await TaskHistoryLogStateManager.list_for_task(session, history.id)
    assert {row.stream for row in rows} == {TaskLogType.STDOUT, TaskLogType.STDERR}
    by_stream = {row.stream: row for row in rows}
    assert (
        by_stream[TaskLogType.STDOUT].producer_offset == EXPECTED_LEGACY_STDOUT_OFFSET
    )
    assert (
        by_stream[TaskLogType.STDERR].producer_offset == EXPECTED_LEGACY_STDERR_OFFSET
    )


@pytest.mark.asyncio
async def test_backfill_legacy_logs_skips_existing_streams(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert streams with an existing state row are left alone."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"pre-existing",
        force_flush=True,
        producer_offset_after=12,
    )
    legacy = {
        "run-script": {
            TaskLogType.STDOUT: "legacy stdout",
            f"{TaskLogType.STDOUT.value}_last_offset": 99,
            TaskLogType.STDERR: "legacy stderr",
            f"{TaskLogType.STDERR.value}_last_offset": 13,
        }
    }
    await backfill_legacy_logs(session, history.id, legacy)
    by_stream = {
        row.stream: row
        for row in await TaskHistoryLogStateManager.list_for_task(session, history.id)
    }
    assert (
        by_stream[TaskLogType.STDOUT].producer_offset
        == EXPECTED_PRE_EXISTING_STDOUT_OFFSET
    )
    assert by_stream[TaskLogType.STDOUT].persisted_offset == len(b"pre-existing")
    assert (
        by_stream[TaskLogType.STDERR].producer_offset
        == EXPECTED_PRE_EXISTING_STDERR_OFFSET
    )
