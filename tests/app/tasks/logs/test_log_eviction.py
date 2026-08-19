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

"""Define tests for the rolling per-stream byte cap in ``TaskHistoryLogWriter``."""

import pytest
from sqlalchemy import update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.config import tasks_settings
from app.tasks.crud import TaskHistoryLogManager, TaskHistoryLogStateManager
from app.tasks.logs.log_reader import iter_task_history_logs
from app.tasks.logs.log_writer import TaskHistoryLogWriter
from app.tasks.models import (
    TaskHistory,
    TaskHistoryLog,
    TaskHistoryLogState,
    TaskLogType,
)

CHUNK_SIZE = 100
SOURCE = "run-script"
STREAM = TaskLogType.STDOUT
SEEDED_CHUNK_COUNT = 10
UNDER_CAP_CHUNK_COUNT = 5
EXPECTED_RETRY_ATTEMPTS = 2
REALLOCATION_EPOCH = 1


@pytest.fixture(autouse=True)
def _reset_tasks_settings():
    """Clear any override snapshot after each test so caps do not leak."""
    yield
    tasks_settings._set_snapshot({})


def _set_cap(cap_bytes: int, max_rows: int = 1000) -> None:
    """Publish a cap/eviction-row override snapshot for the tasks settings proxy."""
    tasks_settings._set_snapshot(
        {
            "LOG_STREAM_CAP_BYTES": cap_bytes,
            "LOG_STREAM_EVICTION_MAX_ROWS": max_rows,
        }
    )


def _chunk_content(index: int) -> bytes:
    """Return distinct ``CHUNK_SIZE`` ASCII bytes for the chunk at ``index``."""
    return bytes([65 + (index % 26)]) * CHUNK_SIZE


async def _seed_chunks(
    session: AsyncSession, task_history_id: int, count: int
) -> bytes:
    """Append ``count`` distinct ``CHUNK_SIZE`` chunks and return the full stream."""
    full = b""
    cursor = 0
    for index in range(count):
        content = _chunk_content(index)
        full += content
        cursor += CHUNK_SIZE
        await TaskHistoryLogWriter.append(
            session,
            task_history_id,
            source=SOURCE,
            stream=STREAM,
            new_bytes=content,
            force_flush=True,
            producer_offset_after=cursor,
        )
    return full


async def _stream_chunks(
    session: AsyncSession, task_history_id: int
) -> list[TaskHistoryLog]:
    """Return this stream's chunk rows ordered by ``start_offset``."""
    result = await session.exec(
        select(TaskHistoryLog)
        .where(
            col(TaskHistoryLog.task_history_id) == task_history_id,
            col(TaskHistoryLog.source) == SOURCE,
            col(TaskHistoryLog.stream) == STREAM,
        )
        .order_by(col(TaskHistoryLog.start_offset))
    )
    return list(result.all())


@pytest.mark.asyncio
async def test_eviction_caps_stream_to_recent_tail(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert chunks at or under ``low_water`` are dropped and the tail survives."""
    history = created_task_with_history
    cap = 250
    _set_cap(cap)

    full = await _seed_chunks(session, history.id, count=10)
    total = len(full)
    low_water = total - cap

    survivors = await _stream_chunks(session, history.id)
    assert all(chunk.end_offset > low_water for chunk in survivors)
    assert survivors[0].start_offset > 0
    retained_bytes = sum(chunk.end_offset - chunk.start_offset for chunk in survivors)
    assert retained_bytes >= cap
    rebuilt = "".join(chunk.content for chunk in survivors)
    assert rebuilt == full[survivors[0].start_offset :].decode("utf-8")


@pytest.mark.asyncio
async def test_append_without_flush_does_not_evict(
    session: AsyncSession, created_task_with_history: TaskHistory, mocker
):
    """Assert an append that does not advance ``persisted_offset`` evicts nothing."""
    history = created_task_with_history
    _set_cap(250)
    await _seed_chunks(session, history.id, count=10)

    spy = mocker.spy(TaskHistoryLogManager, "delete_chunks_below_offset")
    before = await _stream_chunks(session, history.id)

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source=SOURCE,
        stream=STREAM,
        new_bytes=b"tiny",
        producer_offset_after=len(b"".join(_chunk_content(i) for i in range(10)))
        + len(b"tiny"),
    )

    after = await _stream_chunks(session, history.id)
    assert spy.call_count == 0
    assert [c.id for c in after] == [c.id for c in before]


@pytest.mark.asyncio
async def test_stream_under_cap_is_not_evicted(
    session: AsyncSession, created_task_with_history: TaskHistory, mocker
):
    """Assert a stream below the cap triggers no delete at all."""
    history = created_task_with_history
    _set_cap(10_000)
    spy = mocker.spy(TaskHistoryLogManager, "delete_chunks_below_offset")

    await _seed_chunks(session, history.id, count=UNDER_CAP_CHUNK_COUNT)

    chunks = await _stream_chunks(session, history.id)
    assert len(chunks) == UNDER_CAP_CHUNK_COUNT
    assert spy.call_count == 0


@pytest.mark.asyncio
async def test_eviction_is_bounded_per_flush_and_converges(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert each flush deletes at most ``LOG_STREAM_EVICTION_MAX_ROWS`` chunks."""
    history = created_task_with_history
    max_rows = 2
    _set_cap(10**9)
    full = await _seed_chunks(session, history.id, count=SEEDED_CHUNK_COUNT)
    assert len(await _stream_chunks(session, history.id)) == SEEDED_CHUNK_COUNT

    _set_cap(250, max_rows=max_rows)
    cursor = len(full)

    cursor += CHUNK_SIZE
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source=SOURCE,
        stream=STREAM,
        new_bytes=_chunk_content(10),
        force_flush=True,
        producer_offset_after=cursor,
    )
    after_first = await _stream_chunks(session, history.id)
    assert len(after_first) == SEEDED_CHUNK_COUNT + 1 - max_rows
    assert min(chunk.start_offset for chunk in after_first) == max_rows * CHUNK_SIZE

    cursor += CHUNK_SIZE
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source=SOURCE,
        stream=STREAM,
        new_bytes=_chunk_content(11),
        force_flush=True,
        producer_offset_after=cursor,
    )
    after_second = await _stream_chunks(session, history.id)
    assert len(after_second) == SEEDED_CHUNK_COUNT + 2 - 2 * max_rows
    assert (
        min(chunk.start_offset for chunk in after_second) == 2 * max_rows * CHUNK_SIZE
    )


@pytest.mark.asyncio
async def test_lost_version_race_evicts_only_on_winning_commit(
    session: AsyncSession, created_task_with_history: TaskHistory, mocker, monkeypatch
):
    """Assert eviction runs once, on the iteration that wins the version-CAS.

    A concurrent writer bumps the stream's version between this append's state
    read and its CAS, so the first iteration loses, rolls back, and retries.
    Because eviction sits inside the ``if applied:`` branch, the losing
    iteration never stages a delete, so the converged append still evicts
    exactly once — atomically with the winning chunk insert.
    """
    history_id = created_task_with_history.id
    _set_cap(250)
    await _seed_chunks(session, history_id, count=SEEDED_CHUNK_COUNT)

    spy = mocker.spy(TaskHistoryLogManager, "delete_chunks_below_offset")
    baseline = spy.call_count

    original_get = TaskHistoryLogStateManager.get_for_stream
    reads = {"count": 0}

    async def _read_then_race(session, task_history_id, source, stream):
        state = await original_get(session, task_history_id, source, stream)
        reads["count"] += 1
        if state is not None and reads["count"] == 1:
            await session.exec(
                update(TaskHistoryLogState)
                .where(
                    col(TaskHistoryLogState.task_history_id) == task_history_id,
                    col(TaskHistoryLogState.source) == source,
                    col(TaskHistoryLogState.stream) == stream,
                )
                .values(version=state.version + 1)
                .execution_options(synchronize_session=False)
            )
        return state

    monkeypatch.setattr(
        TaskHistoryLogStateManager, "get_for_stream", staticmethod(_read_then_race)
    )

    cursor = SEEDED_CHUNK_COUNT * CHUNK_SIZE + CHUNK_SIZE
    await TaskHistoryLogWriter.append(
        session,
        history_id,
        source=SOURCE,
        stream=STREAM,
        new_bytes=_chunk_content(SEEDED_CHUNK_COUNT),
        force_flush=True,
        producer_offset_after=cursor,
    )

    assert reads["count"] == EXPECTED_RETRY_ATTEMPTS
    assert spy.call_count == baseline + 1
    state = await original_get(session, history_id, SOURCE, STREAM)
    assert state.persisted_offset == cursor


@pytest.mark.asyncio
async def test_evicted_chunk_not_resurrected_by_stale_retry(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert a stale replay neither advances offsets nor revives evicted chunks."""
    history = created_task_with_history
    _set_cap(250)
    await _seed_chunks(session, history.id, count=10)

    before = await _stream_chunks(session, history.id)
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, SOURCE, STREAM
    )
    persisted_before = state.persisted_offset
    producer_before = state.producer_offset

    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source=SOURCE,
        stream=STREAM,
        new_bytes=_chunk_content(9),
        force_flush=True,
        producer_offset_after=producer_before,
    )

    after = await _stream_chunks(session, history.id)
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, SOURCE, STREAM
    )
    assert state.persisted_offset == persisted_before
    assert [c.start_offset for c in after] == [c.start_offset for c in before]


@pytest.mark.asyncio
async def test_drain_preserves_persisted_offset_for_eviction(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``drain_and_reset_producer_frontier`` leaves ``persisted_offset`` intact."""
    history = created_task_with_history
    _set_cap(250)
    await _seed_chunks(session, history.id, count=10)
    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, SOURCE, STREAM
    )
    persisted_before = state.persisted_offset

    await TaskHistoryLogWriter.drain_and_reset_producer_frontier(
        session, history.id, new_producer_epoch=REALLOCATION_EPOCH
    )

    state = await TaskHistoryLogStateManager.get_for_stream(
        session, history.id, SOURCE, STREAM
    )
    assert state.producer_offset == 0
    assert state.persisted_offset == persisted_before


@pytest.mark.asyncio
async def test_cap_hot_override_changes_retained_tail(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert lowering the cap at runtime shrinks the retained tail on next flush."""
    history = created_task_with_history
    _set_cap(10_000)
    full = await _seed_chunks(session, history.id, count=UNDER_CAP_CHUNK_COUNT)
    assert len(await _stream_chunks(session, history.id)) == UNDER_CAP_CHUNK_COUNT

    _set_cap(250)
    cursor = len(full) + CHUNK_SIZE
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source=SOURCE,
        stream=STREAM,
        new_bytes=_chunk_content(UNDER_CAP_CHUNK_COUNT),
        force_flush=True,
        producer_offset_after=cursor,
    )

    survivors = await _stream_chunks(session, history.id)
    low_water = cursor - 250
    assert all(chunk.end_offset > low_water for chunk in survivors)
    assert len(survivors) < UNDER_CAP_CHUNK_COUNT + 1


@pytest.mark.asyncio
async def test_reader_tolerates_truncated_head(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert the reader streams the surviving tail with absolute offsets."""
    history = created_task_with_history
    _set_cap(250)
    full = await _seed_chunks(session, history.id, count=10)

    survivors = await _stream_chunks(session, history.id)
    first_start = survivors[0].start_offset

    logs = [log async for log in iter_task_history_logs(session, history)]
    assert logs
    assert [log.offset for log in logs] == [chunk.end_offset for chunk in survivors]
    assert "".join(log.msg for log in logs) == full[first_start:].decode("utf-8")

    tail = [log async for log in iter_task_history_logs(session, history, tail_lines=1)]
    assert tail
