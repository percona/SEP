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

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils.date_time import utc_now
from app.tasks.crud import (
    TaskHistoryLogManager,
    TaskHistoryLogStateManager,
    TaskHistoryManager,
    TaskManager,
)
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
    TaskLogType,
    TaskWrite,
)
from tests.app.factories import build_task_history, TaskFactory

EXPECTED_HELLOWORLD_LEN = 10
EXPECTED_LEGACY_STDOUT_OFFSET = 42
EXPECTED_LEGACY_STDERR_OFFSET = 5
EXPECTED_PRE_EXISTING_STDOUT_OFFSET = 12
EXPECTED_PRE_EXISTING_STDERR_OFFSET = 13
EXPECTED_MULTI_STREAM_ROW_COUNT = 3
ALLOC_B_PRODUCER_OFFSET = 1_000
EXPECTED_DRAIN_CHUNK_COUNT = 2
ALLOCATION_EPOCH_OLD = 100
ALLOCATION_EPOCH_NEW = 200
ALLOCATION_EPOCH_LIVE = 500


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

    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
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

    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
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

    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
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
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
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
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
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
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
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
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
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
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
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

    Regression test: the in-memory ``initial_offsets`` reset on
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
        producer_fetch_offset_after=50_000,
        producer_epoch=ALLOCATION_EPOCH_OLD,
    )

    await TaskHistoryLogWriter.drain_and_reset_allocation_frontier(
        session, history.id, new_producer_epoch=ALLOCATION_EPOCH_NEW
    )

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.producer_offset == 0
    assert state.producer_fetch_offset == 0
    assert state.producer_epoch == ALLOCATION_EPOCH_NEW
    persisted_after_alloc_a = state.persisted_offset

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"alloc-b content",
        force_flush=True,
        producer_offset_after=ALLOC_B_PRODUCER_OFFSET,
        producer_fetch_offset_after=len(b"alloc-b content"),
        producer_epoch=ALLOCATION_EPOCH_NEW,
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.producer_offset == ALLOC_B_PRODUCER_OFFSET
    assert state.producer_fetch_offset == len(b"alloc-b content")
    assert state.producer_epoch == ALLOCATION_EPOCH_NEW
    assert state.persisted_offset == persisted_after_alloc_a + len(b"alloc-b content")
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
    assert [chunk.content for chunk in chunks] == ["alloc-a content", "alloc-b content"]


@pytest.mark.asyncio
async def test_append_discards_write_from_older_producer_epoch(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert an append whose epoch predates the committed row's epoch is dropped.

    A sync that overlapped a Nomad reschedule carries the superseded
    allocation's bytes; writing them after the frontier was reset to the new
    allocation would corrupt the stream, so the older-epoch write must be
    discarded and the newer-epoch write must still land.
    """
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"epoch-100",
        force_flush=True,
        producer_offset_after=len(b"epoch-100"),
        producer_fetch_offset_after=len(b"epoch-100"),
        producer_epoch=ALLOCATION_EPOCH_OLD,
    )
    await TaskHistoryLogWriter.drain_and_reset_allocation_frontier(
        session, history.id, new_producer_epoch=ALLOCATION_EPOCH_NEW
    )

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"stale-from-dead-alloc",
        force_flush=True,
        producer_offset_after=1_000,
        producer_fetch_offset_after=1_000,
        producer_epoch=ALLOCATION_EPOCH_OLD,
    )

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.producer_epoch == ALLOCATION_EPOCH_NEW
    assert state.producer_offset == 0
    assert state.producer_fetch_offset == 0
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
    assert [chunk.content for chunk in chunks] == ["epoch-100"]

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"fresh-alloc",
        force_flush=True,
        producer_offset_after=len(b"fresh-alloc"),
        producer_fetch_offset_after=len(b"fresh-alloc"),
        producer_epoch=ALLOCATION_EPOCH_NEW,
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state.producer_epoch == ALLOCATION_EPOCH_NEW
    assert state.producer_offset == len(b"fresh-alloc")
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
    assert [chunk.content for chunk in chunks] == ["epoch-100", "fresh-alloc"]


@pytest.mark.asyncio
async def test_append_discard_guard_survives_version_retry(
    session: AsyncSession,
    created_task_with_history: TaskHistory,
    monkeypatch,
):
    """Assert the epoch discard guard fires on a retry iteration, not just the first.

    A reschedule that commits its frontier reset in the window between this
    worker's state read and its version CAS makes the first CAS lose the race.
    The loop must then re-read the advanced row and discard the stale-allocation
    bytes on the *second* iteration rather than writing them. The race is staged
    by making the first ``_persist_state`` perform the concurrent reset and
    report the CAS as lost; the second iteration re-reads the reset row (epoch
    advanced) and the guard drops the stale write.
    """
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"seed",
        force_flush=True,
        producer_offset_after=len(b"seed"),
        producer_fetch_offset_after=len(b"seed"),
        producer_epoch=ALLOCATION_EPOCH_OLD,
    )

    real_persist_state = TaskHistoryLogWriter._persist_state
    persist_calls = {"count": 0}

    async def racing_persist_state(**kwargs):
        persist_calls["count"] += 1
        if persist_calls["count"] == 1:
            await TaskHistoryLogStateManager.reset_allocation_frontier(
                session, history.id, new_producer_epoch=ALLOCATION_EPOCH_NEW
            )
            await session.commit()
            return False
        return await real_persist_state(**kwargs)

    monkeypatch.setattr(
        TaskHistoryLogWriter, "_persist_state", staticmethod(racing_persist_state)
    )

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"stale-through-retry",
        producer_offset_after=1_000,
        producer_fetch_offset_after=1_000,
        producer_epoch=ALLOCATION_EPOCH_OLD,
    )

    assert persist_calls["count"] == 1
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state.producer_epoch == ALLOCATION_EPOCH_NEW
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
    assert [chunk.content for chunk in chunks] == ["seed"]


@pytest.mark.asyncio
async def test_append_discards_stale_first_insert_during_switch(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert a stale first-insert during an allocation switch is fully discarded.

    A brand-new step whose first output arrives right at a reschedule has no
    ``TaskHistoryLogState`` row yet, so the reset's bulk
    UPDATE stamps zero rows. A lagging sync from the *superseded* allocation must
    still be discarded on the first-insert path — no row inserted, no bytes
    flushed — by consulting the task-level allocation-epoch high-water mark. The
    subsequent current-allocation write then lands normally.
    """
    # The discard rolls back to release its lock, which expires the fixture row.
    history_id = created_task_with_history.id
    await TaskHistoryLogWriter.drain_and_reset_allocation_frontier(
        session, history_id, new_producer_epoch=ALLOCATION_EPOCH_NEW
    )

    await TaskHistoryLogWriter.append(
        session,
        history_id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"stale-first-insert",
        force_flush=True,
        producer_offset_after=len(b"stale-first-insert"),
        producer_fetch_offset_after=len(b"stale-first-insert"),
        producer_epoch=ALLOCATION_EPOCH_OLD,
    )
    # Discard must roll back to free the row lock. Assert before any read below,
    # which would autobegin a fresh transaction.
    assert not session.in_transaction()

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history_id, "run-script", TaskLogType.STDOUT
    )
    assert state is None
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history_id)
    assert chunks == []

    await TaskHistoryLogWriter.append(
        session,
        history_id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"current-alloc",
        force_flush=True,
        producer_offset_after=len(b"current-alloc"),
        producer_fetch_offset_after=len(b"current-alloc"),
        producer_epoch=ALLOCATION_EPOCH_NEW,
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history_id, "run-script", TaskLogType.STDOUT
    )
    assert state.producer_epoch == ALLOCATION_EPOCH_NEW
    assert state.producer_offset == len(b"current-alloc")
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history_id)
    assert [chunk.content for chunk in chunks] == ["current-alloc"]


@pytest.mark.asyncio
async def test_append_first_insert_accepts_epoch_at_or_above_hwm(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert a first-insert at or above the task-level high-water mark lands.

    The guard must only drop writes *older* than the current allocation:
    a first-insert whose epoch equals the high-water mark (the live allocation)
    is accepted and stamps the row.
    """
    history = created_task_with_history
    await TaskHistoryLogWriter.drain_and_reset_allocation_frontier(
        session, history.id, new_producer_epoch=ALLOCATION_EPOCH_NEW
    )

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"live-first-insert",
        force_flush=True,
        producer_offset_after=len(b"live-first-insert"),
        producer_fetch_offset_after=len(b"live-first-insert"),
        producer_epoch=ALLOCATION_EPOCH_NEW,
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.producer_epoch == ALLOCATION_EPOCH_NEW
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
    assert [chunk.content for chunk in chunks] == ["live-first-insert"]


@pytest.mark.asyncio
async def test_append_first_insert_without_hwm_accepts_write(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert a first Nomad write with no prior reset (high-water ``0``) lands.

    On the very first allocation no frontier reset has run, so the task-level
    high-water mark is still the ``0`` sentinel. A first-insert carrying a real
    ``CreateIndex`` must be trusted, not discarded.
    """
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"first-alloc",
        force_flush=True,
        producer_offset_after=len(b"first-alloc"),
        producer_fetch_offset_after=len(b"first-alloc"),
        producer_epoch=ALLOCATION_EPOCH_LIVE,
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.producer_epoch == ALLOCATION_EPOCH_LIVE
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
    assert [chunk.content for chunk in chunks] == ["first-alloc"]


@pytest.mark.asyncio
async def test_append_first_insert_discards_when_reset_commits_mid_append(
    session: AsyncSession,
    created_task_with_history: TaskHistory,
    monkeypatch,
):
    """Assert a first-insert re-checks the high-water mark after a mid-append reset.

    Cover the first-insert TOCTOU: a stale-allocation write reads the
    task-level high-water mark, then a frontier reset commits the new
    epoch before the row is inserted. The version-retry loop must re-read the
    (now advanced) high-water mark on the next iteration and discard the stale
    bytes instead of persisting a first row at the old epoch. The race is staged
    by making the first ``_persist_state`` commit the concurrent reset and report
    the insert as lost; the second iteration re-consults the high-water mark and
    the first-insert guard drops the write.
    """
    history_id = created_task_with_history.id

    real_persist_state = TaskHistoryLogWriter._persist_state
    persist_calls = {"count": 0}

    async def racing_persist_state(**kwargs):
        persist_calls["count"] += 1
        if persist_calls["count"] == 1:
            await TaskHistoryLogWriter.drain_and_reset_allocation_frontier(
                session, history_id, new_producer_epoch=ALLOCATION_EPOCH_NEW
            )
            return False
        return await real_persist_state(**kwargs)

    monkeypatch.setattr(
        TaskHistoryLogWriter, "_persist_state", staticmethod(racing_persist_state)
    )

    await TaskHistoryLogWriter.append(
        session,
        history_id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"stale-through-first-insert",
        producer_offset_after=len(b"stale-through-first-insert"),
        producer_fetch_offset_after=len(b"stale-through-first-insert"),
        producer_epoch=ALLOCATION_EPOCH_OLD,
    )

    assert persist_calls["count"] == 1
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history_id, "run-script", TaskLogType.STDOUT
    )
    assert state is None
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history_id)
    assert chunks == []


@pytest.mark.asyncio
async def test_drain_does_not_regress_high_water_mark_on_out_of_order_reset(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert an out-of-order drain with a smaller epoch never lowers the mark.

    Regression for the monotonicity guard in ``bump_log_producer_epoch``: the
    task-level high-water mark must only advance. A stale drain carrying a lower
    ``CreateIndex`` than the current mark is a no-op, so a superseded-allocation
    first-insert stays discarded instead of being re-accepted after the mark is
    clobbered downward.
    """
    history_id = created_task_with_history.id
    await TaskHistoryLogWriter.drain_and_reset_allocation_frontier(
        session, history_id, new_producer_epoch=ALLOCATION_EPOCH_NEW
    )
    assert (
        await TaskHistoryManager.get_log_producer_epoch(session, history_id)
        == ALLOCATION_EPOCH_NEW
    )

    # A late drain from the superseded allocation carries the smaller epoch.
    await TaskHistoryLogWriter.drain_and_reset_allocation_frontier(
        session, history_id, new_producer_epoch=ALLOCATION_EPOCH_OLD
    )
    assert (
        await TaskHistoryManager.get_log_producer_epoch(session, history_id)
        == ALLOCATION_EPOCH_NEW
    )

    # The guard is still anchored to the higher mark: a mid-epoch first-insert
    # (older than NEW, newer than OLD) is discarded, proving the mark did not
    # regress to OLD.
    mid_epoch = (ALLOCATION_EPOCH_OLD + ALLOCATION_EPOCH_NEW) // 2
    await TaskHistoryLogWriter.append(
        session,
        history_id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"mid-epoch-stale",
        force_flush=True,
        producer_offset_after=len(b"mid-epoch-stale"),
        producer_fetch_offset_after=len(b"mid-epoch-stale"),
        producer_epoch=mid_epoch,
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history_id, "run-script", TaskLogType.STDOUT
    )
    assert state is None
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history_id)
    assert chunks == []


@pytest.mark.asyncio
async def test_append_discards_stale_first_insert_across_both_streams(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert both streams of a brand-new step are discarded on a stale first-insert.

    A rescheduled step produces stdout *and* stderr; when its first output for
    each stream lands from the superseded allocation right after the switch,
    neither stream has a ``TaskHistoryLogState`` row yet. The task-level
    high-water mark must discard both first-inserts, then accept both streams'
    current-allocation writes.
    """
    history_id = created_task_with_history.id
    await TaskHistoryLogWriter.drain_and_reset_allocation_frontier(
        session, history_id, new_producer_epoch=ALLOCATION_EPOCH_NEW
    )

    for stream in (TaskLogType.STDOUT, TaskLogType.STDERR):
        await TaskHistoryLogWriter.append(
            session,
            history_id,
            source="run-script",
            stream=stream,
            new_bytes=b"stale-" + stream.value.encode("utf-8"),
            force_flush=True,
            producer_offset_after=len(b"stale-" + stream.value.encode("utf-8")),
            producer_fetch_offset_after=len(b"stale-" + stream.value.encode("utf-8")),
            producer_epoch=ALLOCATION_EPOCH_OLD,
        )
        assert (
            await TaskHistoryLogStateManager.get_for_stream(
                session, history_id, "run-script", stream
            )
            is None
        )
    assert await TaskHistoryLogManager.list_chunks_for_task(session, history_id) == []

    for stream in (TaskLogType.STDOUT, TaskLogType.STDERR):
        payload = b"live-" + stream.value.encode("utf-8")
        await TaskHistoryLogWriter.append(
            session,
            history_id,
            source="run-script",
            stream=stream,
            new_bytes=payload,
            force_flush=True,
            producer_offset_after=len(payload),
            producer_fetch_offset_after=len(payload),
            producer_epoch=ALLOCATION_EPOCH_NEW,
        )
        state = await TaskHistoryLogStateManager.get_for_stream(
            session, history_id, "run-script", stream
        )
        assert state is not None
        assert state.producer_epoch == ALLOCATION_EPOCH_NEW
        assert state.producer_offset == len(payload)


@pytest.mark.asyncio
async def test_append_legacy_epoch_zero_row_accepts_live_write(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert a legacy ``producer_epoch == 0`` row is stamped by the next write.

    Pre-migration rows carry the ``0`` sentinel; the discard guard must treat
    them as trusted and let the first live write advance the epoch to the
    running allocation's ``CreateIndex``.
    """
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"legacy-bytes",
        force_flush=True,
        producer_offset_after=len(b"legacy-bytes"),
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state.producer_epoch == 0

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"live-bytes",
        force_flush=True,
        producer_offset_after=len(b"legacy-bytes") + len(b"live-bytes"),
        producer_fetch_offset_after=len(b"legacy-bytes") + len(b"live-bytes"),
        producer_epoch=ALLOCATION_EPOCH_LIVE,
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state.producer_epoch == ALLOCATION_EPOCH_LIVE
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
    assert [chunk.content for chunk in chunks] == ["legacy-bytes", "live-bytes"]


@pytest.mark.asyncio
async def test_append_non_nomad_caller_leaves_frontier_columns_zero(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert a Celery-shaped append never advances the Nomad frontier columns."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="execution",
        stream=TaskLogType.STDOUT,
        new_bytes=b"celery-output",
        force_flush=True,
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "execution", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.producer_fetch_offset == 0
    assert state.producer_epoch == 0
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
    assert [chunk.content for chunk in chunks] == ["celery-output"]


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


@pytest.mark.asyncio
async def test_append_utf8_boundary_split_is_safe(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert chunk boundaries never land inside a multi-byte UTF-8 codepoint.

    Regression test: the writer used to slice ``staging`` at a
    fixed ``CHUNK_BYTES`` boundary, and ``chunk.decode("utf-8")`` on the
    resulting slice could raise ``UnicodeDecodeError`` if the cut fell in
    the middle of a codepoint.
    """
    history = created_task_with_history
    prefix = b"a" * (CHUNK_BYTES - 2)
    payload = prefix + "\u00e9".encode() + b"tail"
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=payload,
        force_flush=True,
        producer_offset_after=len(payload),
    )
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
    joined = "".join(chunk.content for chunk in chunks)
    assert joined == payload.decode("utf-8")
    for chunk in chunks:
        chunk.content.encode("utf-8")


@pytest.mark.asyncio
async def test_drain_and_reset_flushes_staging_before_zeroing_producer_offset(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert sub-``MIN_FLUSH`` staging is flushed before the producer reset.

    Regression test: the pre-drain reset used to leave
    ``staging`` intact, so the next allocation's bytes were concatenated
    inline with the previous allocation's leftover remainder — producing a
    chunk that mixed content from both allocations. The writer method
    ``drain_and_reset_allocation_frontier`` must emit the remainder as its own
    chunk first, then zero ``producer_offset``.
    """
    history = created_task_with_history
    alloc_a_bytes = b"alloc-a-remainder"
    assert len(alloc_a_bytes) < MIN_FLUSH
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=alloc_a_bytes,
        producer_offset_after=len(alloc_a_bytes),
    )
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.staging == alloc_a_bytes
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
    assert chunks == []

    await TaskHistoryLogWriter.drain_and_reset_allocation_frontier(
        session, history.id, new_producer_epoch=ALLOCATION_EPOCH_NEW
    )

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, "run-script", TaskLogType.STDOUT
    )
    assert state is not None
    assert state.staging == b""
    assert state.producer_offset == 0
    assert state.persisted_offset == len(alloc_a_bytes)

    alloc_b_bytes = b"alloc-b-first-bytes"
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=alloc_b_bytes,
        force_flush=True,
        producer_offset_after=len(alloc_b_bytes),
    )
    chunks = await TaskHistoryLogManager.list_chunks_for_task(session, history.id)
    assert len(chunks) == EXPECTED_DRAIN_CHUNK_COUNT
    assert chunks[0].content == alloc_a_bytes.decode("utf-8")
    assert chunks[1].content == alloc_b_bytes.decode("utf-8")


LOCK_BLOCK_TIMEOUT_SEC = 0.5
RESET_RELEASE_TIMEOUT_SEC = 5


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_first_insert_lock_serialises_reset_on_postgres(
    postgres_engine: AsyncEngine,
):
    """Assert the first-insert ``FOR UPDATE`` lock serialises a concurrent reset on real PG.

    ``with_for_update()`` is a no-op on SQLite, so the rest of this module proves
    the epoch-discard *behaviour* but never the row-lock *ordering* it rests on.
    Here two independent PostgreSQL-bound sessions race: the holder takes the
    first-insert lock via ``get_log_producer_epoch(for_update=True)`` and keeps
    its transaction open; the resetter's ``bump_log_producer_epoch`` + commit
    (the frontier reset) must block until the holder ends, then land — proving the
    two serialise on the ``TaskHistory`` row rather than racing.
    """
    async with postgres_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = get_async_session_maker_from_engine(postgres_engine)
    try:
        async with maker() as seed:
            task = await TaskManager.create(
                seed, TaskWrite.model_validate(TaskFactory.build(name="pg-lock-task"))
            )
            history = await TaskHistoryManager.save(seed, build_task_history(task))
            await seed.commit()
            history_id = history.id

        async with maker() as holder, maker() as resetter:
            # Holder takes the first-insert lock and keeps its transaction open.
            locked_epoch = await TaskHistoryManager.get_log_producer_epoch(
                holder, history_id, for_update=True
            )
            assert locked_epoch == 0

            async def _reset() -> None:
                await TaskHistoryManager.bump_log_producer_epoch(
                    resetter, history_id, new_producer_epoch=ALLOCATION_EPOCH_NEW
                )
                await resetter.commit()

            reset_task = asyncio.ensure_future(_reset())
            # While the holder pins the row, the reset cannot make progress.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(reset_task), timeout=LOCK_BLOCK_TIMEOUT_SEC
                )

            # Release the lock; the serialised reset now converges.
            await holder.rollback()
            await asyncio.wait_for(reset_task, timeout=RESET_RELEASE_TIMEOUT_SEC)

        async with maker() as verify:
            epoch = await TaskHistoryManager.get_log_producer_epoch(verify, history_id)
        assert epoch == ALLOCATION_EPOCH_NEW
    finally:
        async with postgres_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
