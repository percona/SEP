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

"""Define tests for the run-result file reader and recorder seam."""

import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiohttp
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
from app.tasks.execution.exceptions import TaskDataNotFoundInExecutorError
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    Task,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskWrite,
)
from app.tasks.routes import stop_task_history, sync_task_history
from app.tasks.run_result import (
    _read_run_result,
    maybe_record_run,
    RUN_RESULT_FILENAME,
    RUN_RESULT_MAX_BYTES,
)
from tests.app.factories import build_task_history, TaskFactory

_RESULT = {"backup_dir": "/data/x", "size_bytes": 123, "upload_destination": "s3://b/x"}
_OUTPUT_FILES_PATH = "run-script/local/output_files"
_RESULT_PATH = f"{_OUTPUT_FILES_PATH}/{RUN_RESULT_FILENAME}"

_Stream = Callable[..., AsyncGenerator[bytes, None]]


def _result_bytes(result: dict | None = None) -> bytes:
    """Return the encoded JSON a payload would have written for ``result``."""
    return json.dumps(_RESULT if result is None else result).encode()


def _yielding(*chunks: bytes) -> _Stream:
    """Return a ``stream_file`` stand-in yielding ``chunks``."""

    async def _stream(*args, **kwargs) -> AsyncGenerator[bytes, None]:
        del args, kwargs
        for chunk in chunks:
            yield chunk

    return _stream


def _raising(error: Exception, *chunks: bytes) -> _Stream:
    """Return a ``stream_file`` stand-in raising ``error`` after ``chunks``."""

    async def _stream(*args, **kwargs) -> AsyncGenerator[bytes, None]:
        del args, kwargs
        for chunk in chunks:
            yield chunk
        raise error

    return _stream


def _response_error(status_code: int) -> aiohttp.ClientResponseError:
    """Return the error the fs stat endpoint raises for ``status_code``."""
    return aiohttp.ClientResponseError(
        request_info=None, history=(), status=status_code
    )


def _fake_executor(stream: _Stream) -> MagicMock:
    """Return a ``BaseExecutor`` mock whose ``stream_file`` runs ``stream``."""
    executor = MagicMock(spec=BaseExecutor)
    executor.stream_file = MagicMock(side_effect=stream)
    return executor


def _history(output_files_path: str | None = _OUTPUT_FILES_PATH) -> TaskHistory:
    """Return an unsaved terminal history whose task has ``output_files_path``."""
    task = Task(name="recorder-task", output_files_path=output_files_path)
    return build_task_history(task)


class TestReadRunResult:
    """Cover reading a terminal run's result file back through the executor."""

    @pytest.mark.asyncio
    async def test_returns_decoded_result(self) -> None:
        """Decode a result accumulated across chunks, reading it unanonymized."""
        encoded = _result_bytes()
        executor = _fake_executor(_yielding(encoded[:10], encoded[10:]))
        history = _history()

        assert await _read_run_result(executor, history) == _RESULT
        executor.stream_file.assert_called_once_with(
            history, _RESULT_PATH, anonymize=False
        )

    @pytest.mark.parametrize(
        "stream",
        [
            pytest.param(_raising(_response_error(404)), id="missing_file"),
            pytest.param(_yielding(b""), id="empty_file"),
            pytest.param(_yielding(b"{not json"), id="malformed_json"),
            pytest.param(_yielding(b'["not", "an", "object"]'), id="non_object_json"),
            pytest.param(_yielding(b"\xff\xfe not utf-8"), id="undecodable_bytes"),
            pytest.param(
                _yielding(b"x" * (RUN_RESULT_MAX_BYTES + 1)), id="over_size_cap"
            ),
            pytest.param(
                _raising(aiohttp.ClientError(), b'{"backup_dir":'),
                id="mid_read_failure",
            ),
            pytest.param(
                _raising(TaskDataNotFoundInExecutorError("gone")), id="allocation_gone"
            ),
            pytest.param(_raising(NotImplementedError()), id="executor_without_files"),
        ],
    )
    @pytest.mark.asyncio
    async def test_returns_none_when_unreadable(self, stream: _Stream) -> None:
        """Map every shape of "no result to read" to ``None`` without raising."""
        assert await _read_run_result(_fake_executor(stream), _history()) is None

    @pytest.mark.asyncio
    async def test_skips_read_without_output_files_path(self) -> None:
        """Skip the executor entirely for a task that declares no output path."""
        executor = _fake_executor(_yielding(_result_bytes()))

        assert await _read_run_result(executor, _history(None)) is None
        executor.stream_file.assert_not_called()


@asynccontextmanager
async def _recorder_db(*, recorder: str | None, status: TaskHistoryStatusEnum):
    """Yield ``(maker, history_id)`` for a task stamped with ``recorder``.

    Build an in-memory tasks DB with one output-file-producing task carrying
    ``run_result_recorder`` and a history at ``status``.
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
        task.output_files_path = _OUTPUT_FILES_PATH
        task = await TaskManager.save(session, task)
        saved = await TaskHistoryManager.save(
            session, build_task_history(task, status=status)
        )
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
    async def test_recorder_invoked_with_read_result(self, mocker):
        """Invoke the recorder with the result read back from the run's file."""
        calls = []

        async def _recorder(session, history, result):
            calls.append((history.id, result))

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        async with _recorder_db(
            recorder="pkg:rec", status=TaskHistoryStatusEnum.SUCCESS
        ) as (maker, history_id):
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            await maybe_record_run(
                history_id, _fake_executor(_yielding(_result_bytes()))
            )

        assert calls == [(history_id, _RESULT)]

    @pytest.mark.asyncio
    async def test_recorder_invoked_with_none_when_no_result_file(self, mocker):
        """Invoke the recorder with ``None`` when the run wrote no result file."""
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
            await maybe_record_run(
                history_id, _fake_executor(_raising(_response_error(404)))
            )

        assert results == [None]

    @pytest.mark.asyncio
    async def test_no_op_when_no_recorder_stamped(self, mocker):
        """Skip both the file read and the recorder when the task declares none."""
        called = False

        async def _recorder(session, history, result):
            nonlocal called
            called = True

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        executor = _fake_executor(_yielding(_result_bytes()))
        async with _recorder_db(
            recorder=None, status=TaskHistoryStatusEnum.SUCCESS
        ) as (maker, history_id):
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            await maybe_record_run(history_id, executor)

        assert called is False
        executor.stream_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_op_on_non_terminal_status(self, mocker):
        """Skip recording when the history has not reached a terminal status."""
        called = False

        async def _recorder(session, history, result):
            nonlocal called
            called = True

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        executor = _fake_executor(_yielding(_result_bytes()))
        async with _recorder_db(
            recorder="pkg:rec", status=TaskHistoryStatusEnum.RUNNING
        ) as (maker, history_id):
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            await maybe_record_run(history_id, executor)

        assert called is False
        executor.stream_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_swallows_unresolvable_recorder(self, mocker):
        """Suppress (log) an unresolvable recorder path without failing the sync."""
        async with _recorder_db(
            recorder="no.such.module:rec", status=TaskHistoryStatusEnum.SUCCESS
        ) as (maker, history_id):
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            await maybe_record_run(  # must not raise
                history_id, _fake_executor(_yielding(_result_bytes()))
            )

    @pytest.mark.asyncio
    async def test_swallows_recorder_runtime_error(self, mocker):
        """Suppress (log) a recorder that raises without failing the sync."""

        async def _recorder(session, history, result):
            raise RuntimeError("boom")

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        async with _recorder_db(
            recorder="pkg:rec", status=TaskHistoryStatusEnum.SUCCESS
        ) as (maker, history_id):
            mocker.patch(
                "app.tasks.run_result.get_async_session_maker", return_value=maker
            )
            await maybe_record_run(  # must not raise
                history_id, _fake_executor(_yielding(_result_bytes()))
            )


def _flip_status(target: TaskHistoryStatusEnum, *, result: dict | None = None):
    """Return a fake executor that syncs an item to ``target`` and serves ``result``."""

    async def _fake_sync(item, writer_session=None, *, await_annotations=False):
        del writer_session, await_annotations
        item.status = target
        item.finished_at = utc_now()
        return item

    executor = _fake_executor(
        _raising(_response_error(404))
        if result is None
        else _yielding(_result_bytes(result))
    )
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
        """Fire the recorder with the run's result when a run syncs to SUCCESS."""
        recorded = []

        async def _recorder(session, history, result):
            recorded.append(result)

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
                return_value=_flip_status(
                    TaskHistoryStatusEnum.SUCCESS, result=_RESULT
                ),
            )
            await sync_queue_item(history_id)

        assert recorded == [_RESULT]

    @pytest.mark.asyncio
    async def test_records_none_on_non_success_terminal(self, mocker):
        """Fire the recorder with ``None`` when a run syncs to FAILED (no result)."""
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
        """Fire the recorder with the run's result when the route syncs to SUCCESS."""
        recorded = []

        async def _recorder(session, history, result):
            recorded.append(result)

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        async with _recorder_db(
            recorder="pkg:rec", status=TaskHistoryStatusEnum.RUNNING
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
                    executor=_flip_status(
                        TaskHistoryStatusEnum.SUCCESS, result=_RESULT
                    ),
                    task_history=task_history,
                )

        assert recorded == [_RESULT]


class TestStopPathCarveOut:
    """Cover the deliberate exclusion of the stop path from run recording."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self, mocker):
        """Reset the resolver cache before each test."""
        mocker.patch.dict(hook_resolver._RESOLVED, {}, clear=True)

    @pytest.mark.asyncio
    async def test_stopping_a_run_records_nothing(self, mocker):
        """Skip recording for a stopped run: its payload never wrote a result."""
        recorded = []

        async def _recorder(session, history, result):
            recorded.append(result)

        async def _stop(session, item):
            item.status = TaskHistoryStatusEnum.STOPPED
            item.finished_at = utc_now()
            return await TaskHistoryManager.save(session, item)

        mocker.patch.dict(hook_resolver._RESOLVED, {"pkg:rec": _recorder})
        executor = _fake_executor(_yielding(_result_bytes()))
        executor.stop_task = AsyncMock(side_effect=_stop)
        async with _recorder_db(
            recorder="pkg:rec", status=TaskHistoryStatusEnum.RUNNING
        ) as (maker, history_id):
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
                stopped = await stop_task_history(
                    session=session, executor=executor, task_history=task_history
                )

        assert stopped.status == TaskHistoryStatusEnum.STOPPED
        assert recorded == []
        executor.stream_file.assert_not_called()
