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

"""Define tests for the run-result marker parser and recorder seam."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import undefer
from sqlmodel import SQLModel
from sqlmodel.pool import StaticPool

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer, utc_now
from app.tasks import hook_resolver
from app.tasks.celery import sync_queue_item
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.execution.models import BaseExecutor
from app.tasks.logs.log_writer import TaskHistoryLogWriter
from app.tasks.models import (
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLogType,
    TaskWrite,
)
from app.tasks.routes import sync_task_history
from app.tasks.run_result import maybe_record_run, parse_run_result, RUN_RESULT_MARKER
from tests.app.factories import build_task_history, TaskFactory

_RESULT = {"backup_dir": "/data/x", "size_bytes": 123, "upload_destination": "s3://b/x"}


def _marker_line(result: dict) -> bytes:
    """Return one encoded marker log line for ``result``."""
    return f"{RUN_RESULT_MARKER}{json.dumps(result, separators=(',', ':'))}\n".encode()


async def _append(
    session,
    history_id: int,
    *chunks: bytes,
    stream: TaskLogType = TaskLogType.STDOUT,
    source: str = "run-script",
) -> None:
    """Append each chunk as a flushed log record with a running per-stream cursor."""
    cursor = 0
    for data in chunks:
        cursor += len(data)
        await TaskHistoryLogWriter.append(
            session,
            history_id,
            source=source,
            stream=stream,
            new_bytes=data,
            force_flush=True,
            producer_offset_after=cursor,
        )


class TestParseRunResult:
    """Cover reassembling and decoding the result marker from persisted logs."""

    @pytest.mark.asyncio
    async def test_returns_marker_dict(
        self, session, created_task_with_history: TaskHistory
    ) -> None:
        """Return the decoded dict for a single well-formed marker line."""
        history = created_task_with_history
        await _append(session, history.id, b"starting backup\n", _marker_line(_RESULT))

        assert await parse_run_result(session, history) == _RESULT

    @pytest.mark.asyncio
    async def test_reassembles_marker_split_across_chunks(
        self, session, created_task_with_history: TaskHistory
    ) -> None:
        """Parse a marker line whose bytes straddle a chunk boundary."""
        history = created_task_with_history
        line = _marker_line(_RESULT)
        split = len(RUN_RESULT_MARKER) + 8
        await _append(session, history.id, line[:split], line[split:])

        assert await parse_run_result(session, history) == _RESULT

    @pytest.mark.asyncio
    async def test_returns_none_without_marker(
        self, session, created_task_with_history: TaskHistory
    ) -> None:
        """Return ``None`` when no marker line is present."""
        history = created_task_with_history
        await _append(session, history.id, b"just some ordinary\nlog output\n")

        assert await parse_run_result(session, history) is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unparseable_json(
        self, session, created_task_with_history: TaskHistory
    ) -> None:
        """Return ``None`` (logged) when the marker payload is not valid JSON."""
        history = created_task_with_history
        await _append(session, history.id, f"{RUN_RESULT_MARKER}{{not json\n".encode())

        assert await parse_run_result(session, history) is None

    @pytest.mark.asyncio
    async def test_returns_last_of_multiple_markers(
        self, session, created_task_with_history: TaskHistory
    ) -> None:
        """Return the last marker (logged) when several are emitted."""
        history = created_task_with_history
        second = {**_RESULT, "backup_dir": "/data/second"}
        await _append(session, history.id, _marker_line(_RESULT), _marker_line(second))

        assert await parse_run_result(session, history) == second

    @pytest.mark.asyncio
    async def test_ignores_sentinel_on_stderr(
        self, session, created_task_with_history: TaskHistory
    ) -> None:
        """Ignore a sentinel that appears on stderr rather than stdout."""
        history = created_task_with_history
        await _append(
            session, history.id, _marker_line(_RESULT), stream=TaskLogType.STDERR
        )

        assert await parse_run_result(session, history) is None


@asynccontextmanager
async def _recorder_db(
    *,
    recorder: str | None,
    status: TaskHistoryStatusEnum,
    marker: bytes | None = None,
):
    """Yield ``(maker, history_id)`` for a task stamped with ``recorder``.

    Build an in-memory tasks DB with one task carrying ``run_result_recorder``
    and a history at ``status``, optionally seeding a stdout ``marker`` chunk.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = get_async_session_maker_from_engine(engine)
    async with maker() as session:
        task = await TaskManager.create(
            session,
            TaskWrite.model_validate(
                TaskFactory.build(name="recorder-task", run_result_recorder=recorder)
            ),
        )
        saved = await TaskHistoryManager.save(
            session, build_task_history(task, status=status)
        )
        if marker is not None:
            await _append(session, saved.id, marker)
        history_id = saved.id
    try:
        yield maker, history_id
    finally:
        await engine.dispose()


class TestMaybeRecordRun:
    """Cover resolving and invoking the per-task recorder at terminal status."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self, mocker):
        """Reset the resolver cache before each test."""
        mocker.patch.dict(hook_resolver._RESOLVED, {}, clear=True)

    @pytest.mark.asyncio
    async def test_recorder_invoked_on_success_with_parsed_dict(self, mocker):
        """Invoke the recorder with the parsed marker dict on a successful run."""
        calls = []

        async def _recorder(session, history, result):
            calls.append((history.id, result))

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        async with _recorder_db(
            recorder="pkg:rec",
            status=TaskHistoryStatusEnum.SUCCESS,
            marker=_marker_line(_RESULT),
        ) as (maker, history_id):
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            await maybe_record_run(history_id)

        assert calls == [(history_id, _RESULT)]

    @pytest.mark.asyncio
    async def test_recorder_invoked_with_none_on_non_success(self, mocker):
        """Invoke the recorder with ``None`` when a non-success run emits no marker."""
        results = []

        async def _recorder(session, history, result):
            results.append(result)

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        async with _recorder_db(
            recorder="pkg:rec", status=TaskHistoryStatusEnum.FAILED
        ) as (maker, history_id):
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            await maybe_record_run(history_id)

        assert results == [None]

    @pytest.mark.asyncio
    async def test_no_op_when_no_recorder_stamped(self, mocker):
        """Skip recording when the task declares no recorder."""
        called = False

        async def _recorder(session, history, result):
            nonlocal called
            called = True

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        async with _recorder_db(
            recorder=None, status=TaskHistoryStatusEnum.SUCCESS
        ) as (maker, history_id):
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            await maybe_record_run(history_id)

        assert called is False

    @pytest.mark.asyncio
    async def test_no_op_on_non_terminal_status(self, mocker):
        """Skip recording when the history has not reached a terminal status."""
        called = False

        async def _recorder(session, history, result):
            nonlocal called
            called = True

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        async with _recorder_db(
            recorder="pkg:rec", status=TaskHistoryStatusEnum.RUNNING
        ) as (maker, history_id):
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            await maybe_record_run(history_id)

        assert called is False

    @pytest.mark.asyncio
    async def test_swallows_unresolvable_recorder(self, mocker):
        """Suppress (log) an unresolvable recorder path without failing the sync."""
        async with _recorder_db(
            recorder="no.such.module:rec", status=TaskHistoryStatusEnum.SUCCESS
        ) as (maker, history_id):
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            await maybe_record_run(history_id)  # must not raise

    @pytest.mark.asyncio
    async def test_swallows_recorder_runtime_error(self, mocker):
        """Suppress (log) a recorder that raises without failing the sync."""

        async def _recorder(session, history, result):
            raise RuntimeError("boom")

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        async with _recorder_db(
            recorder="pkg:rec",
            status=TaskHistoryStatusEnum.SUCCESS,
            marker=_marker_line(_RESULT),
        ) as (maker, history_id):
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            await maybe_record_run(history_id)  # must not raise


def _flip_status(target: TaskHistoryStatusEnum):
    """Return a fake ``executor.sync_task_history`` that flips the item to ``target``."""

    async def _fake_sync(item, writer_session=None, *, await_annotations=False):
        del writer_session, await_annotations
        item.status = target
        item.finished_at = utc_now()
        return item

    executor = MagicMock(spec=BaseExecutor)
    executor.sync_task_history = AsyncMock(side_effect=_fake_sync)
    return executor


class TestSyncQueueItemSeam:
    """Cover the recorder firing end-to-end through the ``sync_queue_item`` seam."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self, mocker):
        """Reset the resolver cache before each test."""
        mocker.patch.dict(hook_resolver._RESOLVED, {}, clear=True)

    @pytest.mark.asyncio
    async def test_records_run_result_on_success(self, mocker):
        """Fire the recorder with the parsed marker when a run syncs to SUCCESS."""
        recorded = []

        async def _recorder(session, history, result):
            recorded.append(result)

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        async with _recorder_db(
            recorder="pkg:rec",
            status=TaskHistoryStatusEnum.RUNNING,
            marker=_marker_line(_RESULT),
        ) as (maker, history_id):
            mocker.patch("app.tasks.celery.get_async_session_maker", return_value=maker)
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            mocker.patch(
                "app.tasks.celery.get_executor_for_task",
                return_value=_flip_status(TaskHistoryStatusEnum.SUCCESS),
            )
            await sync_queue_item(history_id)

        assert recorded == [_RESULT]

    @pytest.mark.asyncio
    async def test_records_none_on_non_success_terminal(self, mocker):
        """Fire the recorder with ``None`` when a run syncs to FAILED (no marker)."""
        results = []

        async def _recorder(session, history, result):
            results.append(result)

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        async with _recorder_db(
            recorder="pkg:rec", status=TaskHistoryStatusEnum.RUNNING
        ) as (maker, history_id):
            mocker.patch("app.tasks.celery.get_async_session_maker", return_value=maker)
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            mocker.patch(
                "app.tasks.celery.get_executor_for_task",
                return_value=_flip_status(TaskHistoryStatusEnum.FAILED),
            )
            await sync_queue_item(history_id)

        assert results == [None]


class TestSyncRouteSeam:
    """Cover the recorder firing end-to-end through the ``POST /history/{id}/sync/`` seam."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self, mocker):
        """Reset the resolver cache before each test."""
        mocker.patch.dict(hook_resolver._RESOLVED, {}, clear=True)

    @pytest.mark.asyncio
    async def test_records_run_result_on_success(self, mocker):
        """Fire the recorder with the parsed marker when the route syncs to SUCCESS."""
        recorded = []

        async def _recorder(session, history, result):
            recorded.append(result)

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        async with _recorder_db(
            recorder="pkg:rec",
            status=TaskHistoryStatusEnum.RUNNING,
            marker=_marker_line(_RESULT),
        ) as (maker, history_id):
            mocker.patch("app.tasks.routes.get_async_session_maker", return_value=maker)
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            async with maker() as session:
                task_history = await TaskHistoryManager.get_or_404(
                    session,
                    select_related=(TaskHistory.task,),
                    query_options=[undefer(TaskHistory.execution_request)],
                    id=history_id,
                )
                await sync_task_history(
                    session=session,
                    executor=_flip_status(TaskHistoryStatusEnum.SUCCESS),
                    task_history=task_history,
                )

        assert recorded == [_RESULT]
