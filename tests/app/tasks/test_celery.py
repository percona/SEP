"""Define tests for the app.tasks.celery module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import HTTPBadRequestException, HTTPConflictException
from app.tasks.celery import _dispatch_chained_task, _MAX_CHAIN_DEPTH, sync_queue_item
from app.tasks.models import (
    DispatchLock,
    Task,
    TaskBackendEnum,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
)
from tests.app.factories import TaskFactory


def _make_task(**overrides):
    """Build a fake Task instance with sensible defaults."""
    defaults = {
        "id": 1,
        "name": "test-task",
        "data": {"Constraints": [{"RTarget": "node-1"}]},
        "backend": TaskBackendEnum.NOMAD,
        "owner": "ANY",
        "is_template": False,
        "protected": False,
        "alert_on_fail": False,
    }
    defaults.update(overrides)
    return Task(**defaults)


def _make_history(task=None, **overrides):
    """Build a fake TaskHistory instance with sensible defaults."""
    task = task or _make_task()
    defaults = {
        "id": 10,
        "task_id": task.id,
        "task": task,
        "status": TaskHistoryStatusEnum.PENDING,
        "execution_request": TaskExecutionRequest(
            task=task.name,
            target="node-1",
            meta={"key": "value"},
            payload=None,
        ),
        "executed_by": "test-user",
    }
    defaults.update(overrides)
    return TaskHistory(**defaults)


def _make_session_mock():
    """Build a mock AsyncSession with a bind that returns a name."""
    session = AsyncMock()
    bind = MagicMock()
    bind.name = "sqlite"
    session.get_bind = MagicMock(return_value=bind)
    return session


def _make_lock_session_maker():
    """Build a mock async session maker that yields an async context manager."""
    lock_session = AsyncMock()
    lock_session_cm = AsyncMock()
    lock_session_cm.__aenter__ = AsyncMock(return_value=lock_session)
    lock_session_cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=lock_session_cm)


def _make_chain_task(name: str) -> Task:
    """Build an in-memory Task for chain dispatch tests."""
    return TaskFactory.build(
        name=name,
        backend=TaskBackendEnum.NOMAD,
        data={"meta": {"target": "host1"}},
    )


def _make_chain_history(
    task: Task, status: TaskHistoryStatusEnum, meta: dict
) -> TaskHistory:
    """Build an in-memory TaskHistory for chain dispatch tests."""
    history = TaskHistory(
        task_id=task.id or 1,
        task=task,
        execution_request=TaskExecutionRequest(
            task=task.name,
            target="host1",
            meta=meta,
            payload=None,
            tracking={"evaluation_id": ""},
        ),
        status=status,
        executed_by="test-user",
        anonymize_mask=None,
    )
    history.id = 1
    return history


def _make_chain_session_mock() -> tuple[MagicMock, AsyncMock]:
    """Return (session_maker_mock, session_mock) for chain dispatch tests."""
    session_mock = AsyncMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    session_maker = MagicMock()
    session_maker.return_value = session_mock
    return session_maker, session_mock


class TestGetExecutorForTask:
    """Test get_executor_for_task."""

    def test_nomad_backend_returns_executor(self):
        """Assert NOMAD backend returns an executor from get_executor."""
        from app.tasks.celery import get_executor_for_task

        task = _make_task(backend=TaskBackendEnum.NOMAD)
        mock_executor = MagicMock()
        with patch(
            "app.tasks.celery.get_executor", return_value=mock_executor
        ) as mock_get:
            result = get_executor_for_task(task)

        mock_get.assert_called_once_with(TaskBackendEnum.NOMAD)
        assert result is mock_executor

    def test_unsupported_backend_raises_bad_request(self):
        """Assert unsupported backend raises HTTPBadRequestException."""
        from app.tasks.celery import get_executor_for_task

        task = _make_task(backend=TaskBackendEnum.NOMAD)
        with (
            patch(
                "app.tasks.celery.get_executor",
                side_effect=ValueError("Unsupported"),
            ),
            pytest.raises(HTTPBadRequestException, match="Unsupported task backend"),
        ):
            get_executor_for_task(task)


class TestDispatchQueueItem:
    """Test dispatch_queue_item."""

    @pytest.mark.asyncio
    async def test_with_session_provided(self):
        """Assert provided session is passed to _dispatch_queue_item."""
        from app.tasks.celery import dispatch_queue_item

        queue_item = _make_history()
        session = _make_session_mock()
        expected = _make_history(status=TaskHistoryStatusEnum.RUNNING)

        with patch(
            "app.tasks.celery._dispatch_queue_item",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_dispatch:
            result = await dispatch_queue_item(queue_item, session=session)

        mock_dispatch.assert_awaited_once_with(queue_item, session)
        assert result is expected

    @pytest.mark.asyncio
    async def test_without_session_creates_own(self):
        """Assert a new session is created when none is provided."""
        from app.tasks.celery import dispatch_queue_item

        queue_item = _make_history()
        expected = _make_history(status=TaskHistoryStatusEnum.RUNNING)

        with (
            patch(
                "app.tasks.celery.get_async_session_maker",
                return_value=_make_lock_session_maker(),
            ),
            patch(
                "app.tasks.celery._dispatch_queue_item",
                new_callable=AsyncMock,
                return_value=expected,
            ) as mock_dispatch,
        ):
            result = await dispatch_queue_item(queue_item, session=None)

        mock_dispatch.assert_awaited_once()
        assert result is expected


class TestInternalDispatchQueueItem:
    """Test _dispatch_queue_item."""

    @pytest.mark.asyncio
    async def test_non_pending_raises_conflict(self):
        """Assert non-PENDING status raises HTTPConflictException."""
        from app.tasks.celery import _dispatch_queue_item

        queue_item = _make_history(status=TaskHistoryStatusEnum.RUNNING)
        session = _make_session_mock()

        with pytest.raises(HTTPConflictException, match="not in a pending state"):
            await _dispatch_queue_item(queue_item, session)

    @pytest.mark.asyncio
    async def test_happy_path_dispatches_and_cleans_lock(self):
        """Assert happy path creates lock, dispatches, and cleans lock."""
        from app.tasks.celery import _dispatch_queue_item

        task = _make_task()
        queue_item = _make_history(task=task)
        session = _make_session_mock()
        mock_executor = AsyncMock()
        dispatched_item = _make_history(task=task, status=TaskHistoryStatusEnum.RUNNING)
        mock_executor.dispatch_task.return_value = dispatched_item
        mock_lock = MagicMock(spec=DispatchLock)

        with (
            patch(
                "app.tasks.celery.get_async_session_maker",
                return_value=_make_lock_session_maker(),
            ),
            patch(
                "app.tasks.celery.DispatchLockManager.delete_where",
                new_callable=AsyncMock,
            ),
            patch(
                "app.tasks.celery.DispatchLockManager.create",
                new_callable=AsyncMock,
                return_value=mock_lock,
            ),
            patch(
                "app.tasks.celery._raise_if_identical_task_conflict",
                new_callable=AsyncMock,
            ),
            patch(
                "app.tasks.celery.TaskManager.get_root_task",
                new_callable=AsyncMock,
                return_value=task,
            ),
            patch(
                "app.tasks.celery.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch(
                "app.tasks.celery.DispatchLockManager.delete",
                new_callable=AsyncMock,
            ) as mock_delete_lock,
        ):
            result = await _dispatch_queue_item(queue_item, session)

        assert result is dispatched_item
        mock_delete_lock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_integrity_error_on_lock_raises_conflict(self):
        """Assert IntegrityError on lock creation raises HTTPConflictException."""
        from app.tasks.celery import _dispatch_queue_item

        queue_item = _make_history()
        session = _make_session_mock()

        with (
            patch(
                "app.tasks.celery.get_async_session_maker",
                return_value=_make_lock_session_maker(),
            ),
            patch(
                "app.tasks.celery.DispatchLockManager.delete_where",
                new_callable=AsyncMock,
            ),
            patch(
                "app.tasks.celery.DispatchLockManager.create",
                new_callable=AsyncMock,
                side_effect=IntegrityError(
                    statement="INSERT", params={}, orig=Exception()
                ),
            ),
            pytest.raises(
                HTTPConflictException, match="Identical dispatch in progress"
            ),
        ):
            await _dispatch_queue_item(queue_item, session)

    @pytest.mark.asyncio
    async def test_executor_failure_still_cleans_lock(self):
        """Assert lock is cleaned up even when executor dispatch fails."""
        from app.tasks.celery import _dispatch_queue_item

        task = _make_task()
        queue_item = _make_history(task=task)
        session = _make_session_mock()
        mock_executor = AsyncMock()
        mock_executor.dispatch_task.side_effect = RuntimeError("dispatch failed")
        mock_lock = MagicMock(spec=DispatchLock)

        with (
            patch(
                "app.tasks.celery.get_async_session_maker",
                return_value=_make_lock_session_maker(),
            ),
            patch(
                "app.tasks.celery.DispatchLockManager.delete_where",
                new_callable=AsyncMock,
            ),
            patch(
                "app.tasks.celery.DispatchLockManager.create",
                new_callable=AsyncMock,
                return_value=mock_lock,
            ),
            patch(
                "app.tasks.celery._raise_if_identical_task_conflict",
                new_callable=AsyncMock,
            ),
            patch(
                "app.tasks.celery.TaskManager.get_root_task",
                new_callable=AsyncMock,
                return_value=task,
            ),
            patch(
                "app.tasks.celery.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch(
                "app.tasks.celery.DispatchLockManager.delete",
                new_callable=AsyncMock,
            ) as mock_delete_lock,
            pytest.raises(RuntimeError, match="dispatch failed"),
        ):
            await _dispatch_queue_item(queue_item, session)

        mock_delete_lock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_identical_task_conflict_raises(self):
        """Assert identical running task conflict raises HTTPConflictException."""
        from app.tasks.celery import _dispatch_queue_item

        task = _make_task()
        queue_item = _make_history(task=task)
        session = _make_session_mock()
        mock_lock = MagicMock(spec=DispatchLock)

        with (
            patch(
                "app.tasks.celery.get_async_session_maker",
                return_value=_make_lock_session_maker(),
            ),
            patch(
                "app.tasks.celery.DispatchLockManager.delete_where",
                new_callable=AsyncMock,
            ),
            patch(
                "app.tasks.celery.DispatchLockManager.create",
                new_callable=AsyncMock,
                return_value=mock_lock,
            ),
            patch(
                "app.tasks.celery._raise_if_identical_task_conflict",
                new_callable=AsyncMock,
                side_effect=HTTPConflictException(
                    "Identical queue item already running"
                ),
            ),
            patch(
                "app.tasks.celery.DispatchLockManager.delete",
                new_callable=AsyncMock,
            ) as mock_delete_lock,
            pytest.raises(
                HTTPConflictException, match="Identical queue item already running"
            ),
        ):
            await _dispatch_queue_item(queue_item, session)

        mock_delete_lock.assert_awaited_once()


class TestRaiseIfIdenticalTaskConflict:
    """Test _raise_if_identical_task_conflict."""

    @pytest.mark.asyncio
    async def test_no_identical_task_passes(self):
        """Assert no exception when no identical task exists."""
        from app.tasks.celery import _raise_if_identical_task_conflict

        queue_item = _make_history()
        session = _make_session_mock()

        with patch(
            "app.tasks.celery.TaskHistoryManager.first",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await _raise_if_identical_task_conflict(queue_item, session)

    @pytest.mark.asyncio
    async def test_identical_task_raises_conflict(self):
        """Assert HTTPConflictException when identical task is found."""
        from app.tasks.celery import _raise_if_identical_task_conflict

        queue_item = _make_history()
        session = _make_session_mock()
        identical = _make_history(id=99)

        with (
            patch(
                "app.tasks.celery.TaskHistoryManager.first",
                new_callable=AsyncMock,
                return_value=identical,
            ),
            pytest.raises(
                HTTPConflictException, match="Identical queue item already running"
            ),
        ):
            await _raise_if_identical_task_conflict(queue_item, session)

    @pytest.mark.asyncio
    async def test_no_meta_passes_empty_clauses(self):
        """Assert empty meta produces no extra where clauses."""
        from app.tasks.celery import _raise_if_identical_task_conflict

        task = _make_task()
        queue_item = _make_history(
            task=task,
            execution_request=TaskExecutionRequest(
                task=task.name,
                target="node-1",
                meta=None,
                payload=None,
            ),
        )
        session = _make_session_mock()

        with patch(
            "app.tasks.celery.TaskHistoryManager.first",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await _raise_if_identical_task_conflict(queue_item, session)


class TestDeleteTaskHistory:
    """Test delete_task_history."""

    @pytest.mark.asyncio
    async def test_calls_delete_where_with_queue_id(self):
        """Assert TaskHistoryManager.delete_where is called with correct ID."""
        from app.tasks.celery import delete_task_history

        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker = MagicMock(return_value=mock_session_cm)

        with (
            patch(
                "app.tasks.celery.get_async_session_maker",
                return_value=mock_session_maker,
            ),
            patch(
                "app.tasks.celery.TaskHistoryManager.delete_where",
                new_callable=AsyncMock,
            ) as mock_delete,
        ):
            await delete_task_history(42)

        mock_delete.assert_awaited_once_with(mock_session, id=42)


class TestPreparePeriodicTaskHistory:
    """Test prepare_periodic_task_history."""

    @pytest.mark.asyncio
    async def test_with_execution_data(self):
        """Assert execution_data is validated via PeriodicTaskExecuteRequest."""
        from app.tasks.celery import prepare_periodic_task_history

        task = _make_task()
        expected_history = _make_history(task=task)

        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker = MagicMock(return_value=mock_session_cm)

        exec_data = {"meta": {"target": "node-1"}}

        with (
            patch(
                "app.tasks.celery.get_async_session_maker",
                return_value=mock_session_maker,
            ),
            patch(
                "app.tasks.celery.get_executable_task_by_name",
                new_callable=AsyncMock,
                return_value=task,
            ) as mock_get_task,
            patch(
                "app.tasks.celery.prepare_task_history",
                return_value=expected_history,
            ) as mock_prepare,
        ):
            result = await prepare_periodic_task_history("test-task", exec_data)

        mock_get_task.assert_awaited_once_with(mock_session, "test-task")
        mock_prepare.assert_called_once()
        assert result is expected_history
        call_kwargs = mock_prepare.call_args
        assert call_kwargs[0][0] is task
        assert call_kwargs[1]["executed_by"] == "SYSTEM"
        assert call_kwargs[1]["execution_data"] is not None

    @pytest.mark.asyncio
    async def test_without_execution_data(self):
        """Assert None execution_data passes None to prepare_task_history."""
        from app.tasks.celery import prepare_periodic_task_history

        task = _make_task()
        expected_history = _make_history(task=task)

        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker = MagicMock(return_value=mock_session_cm)

        with (
            patch(
                "app.tasks.celery.get_async_session_maker",
                return_value=mock_session_maker,
            ),
            patch(
                "app.tasks.celery.get_executable_task_by_name",
                new_callable=AsyncMock,
                return_value=task,
            ),
            patch(
                "app.tasks.celery.prepare_task_history",
                return_value=expected_history,
            ) as mock_prepare,
        ):
            result = await prepare_periodic_task_history("test-task", None)

        assert result is expected_history
        call_kwargs = mock_prepare.call_args
        assert call_kwargs[1]["execution_data"] is None


class TestSyncRunningItems:
    """Test sync_running_items."""

    @pytest.mark.asyncio
    async def test_dispatches_sync_for_running_tasks(self):
        """Assert sync tasks are dispatched in chunks for running items."""
        from app.tasks.celery import sync_running_items

        mock_chunks = MagicMock()
        mock_chunks.apply_async = MagicMock()

        with (
            patch(
                "app.tasks.celery.get_async_session_maker",
                return_value=_make_lock_session_maker(),
            ),
            patch(
                "app.tasks.celery.TaskHistoryManager.update_where",
                new_callable=AsyncMock,
                return_value=[1, 2, 3],
            ),
            patch("app.tasks.celery.sync_task_history") as mock_sync_task,
        ):
            mock_sync_task.chunks.return_value = mock_chunks
            await sync_running_items()

        mock_sync_task.chunks.assert_called_once_with([(1,), (2,), (3,)], 100)
        mock_chunks.apply_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_running_tasks_skips_dispatch(self):
        """Assert no dispatch happens when no running tasks found."""
        from app.tasks.celery import sync_running_items

        with (
            patch(
                "app.tasks.celery.get_async_session_maker",
                return_value=_make_lock_session_maker(),
            ),
            patch(
                "app.tasks.celery.TaskHistoryManager.update_where",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("app.tasks.celery.sync_task_history") as mock_sync_task,
        ):
            await sync_running_items()

        mock_sync_task.chunks.assert_not_called()


class TestTaskRevokedHandler:
    """Test task_revoked_handler."""

    def test_execute_task_queue_expired_deletes_history(self):
        """Assert expired execute_task_queue calls delete_task_history."""
        from app.tasks.celery import task_revoked_handler

        request = MagicMock()
        request.args = [42]
        request.kwargs = {}
        request.get.return_value = "app.tasks.celery.execute_task_queue"

        with patch("app.tasks.celery.celery") as mock_celery:
            mock_celery.loop.run_until_complete = MagicMock()
            task_revoked_handler(
                sender=None, request=request, expired=True, signum=None
            )

        mock_celery.loop.run_until_complete.assert_called_once()

    def test_not_execute_task_queue_is_noop(self):
        """Assert non-execute_task_queue task does not call delete."""
        from app.tasks.celery import task_revoked_handler

        request = MagicMock()
        request.args = [42]
        request.kwargs = {}
        request.get.return_value = "app.tasks.celery.some_other_task"

        with patch("app.tasks.celery.celery") as mock_celery:
            mock_celery.loop.run_until_complete = MagicMock()
            task_revoked_handler(
                sender=None, request=request, expired=True, signum=None
            )

        mock_celery.loop.run_until_complete.assert_not_called()

    def test_not_expired_is_noop(self):
        """Assert non-expired revocation does not call delete."""
        from app.tasks.celery import task_revoked_handler

        request = MagicMock()
        request.args = [42]
        request.kwargs = {}
        request.get.return_value = "app.tasks.celery.execute_task_queue"

        with patch("app.tasks.celery.celery") as mock_celery:
            mock_celery.loop.run_until_complete = MagicMock()
            task_revoked_handler(
                sender=None, request=request, expired=False, signum=None
            )

        mock_celery.loop.run_until_complete.assert_not_called()

    def test_queue_id_from_kwargs(self):
        """Assert queue_id is extracted from kwargs when args is empty."""
        from app.tasks.celery import task_revoked_handler

        request = MagicMock()
        request.args = []
        request.kwargs = {"queue_id": 99}
        request.get.return_value = "app.tasks.celery.execute_task_queue"

        with patch("app.tasks.celery.celery") as mock_celery:
            mock_celery.loop.run_until_complete = MagicMock()
            task_revoked_handler(
                sender=None, request=request, expired=True, signum=None
            )

        mock_celery.loop.run_until_complete.assert_called_once()


class TestExecuteTaskQueue:
    """Test execute_task_queue Celery task."""

    def test_executes_and_returns_encoded_result(self):
        """Assert execute_task_queue calls get_task_history and dispatch."""
        from app.tasks import celery as celery_module

        task_obj = _make_task()
        queue_item = _make_history(task=task_obj)
        dispatched = _make_history(task=task_obj, status=TaskHistoryStatusEnum.RUNNING)

        call_order = []

        async def mock_get_task_history(qid):
            call_order.append(("get_task_history", qid))
            return queue_item

        async def mock_dispatch(item):
            call_order.append(("dispatch_queue_item", item.id))
            return dispatched

        test_loop = asyncio.new_event_loop()

        with (
            patch.object(
                celery_module,
                "get_task_history",
                side_effect=mock_get_task_history,
            ),
            patch.object(
                celery_module,
                "dispatch_queue_item",
                side_effect=mock_dispatch,
            ),
            patch.object(
                celery_module.celery,
                "loop",
                test_loop,
            ),
        ):
            result = celery_module.execute_task_queue.__wrapped__(10)

        test_loop.close()

        assert isinstance(result, dict)
        assert ("get_task_history", 10) in call_order
        assert ("dispatch_queue_item", queue_item.id) in call_order


class TestDispatchChainedTask:
    """Test _dispatch_chained_task."""

    @pytest.mark.asyncio
    async def test_dispatches_on_success(self) -> None:
        """Assert _dispatch_chained_task dispatches the chained task when found."""
        main_task = _make_chain_task("main-task")
        chain_task = _make_chain_task("chain-task")
        parent_history = _make_chain_history(
            main_task,
            TaskHistoryStatusEnum.SUCCESS,
            {"chain_task_name": chain_task.name},
        )

        session_maker, _ = _make_chain_session_mock()

        with (
            patch(
                "app.tasks.celery.get_async_session_maker", return_value=session_maker
            ),
            patch(
                "app.tasks.celery.TaskManager.first", new_callable=AsyncMock
            ) as mock_task_first,
            patch(
                "app.tasks.celery.dispatch_queue_item", new_callable=AsyncMock
            ) as mock_dispatch,
        ):
            mock_task_first.return_value = chain_task
            mock_dispatch.return_value = AsyncMock()

            await _dispatch_chained_task(chain_task.name, parent_history)

        mock_dispatch.assert_awaited_once()
        dispatched_history = mock_dispatch.call_args[0][0]
        assert dispatched_history.execution_request.target == "host1"
        assert dispatched_history.execution_request.meta.get("chain_depth") == 1

    @pytest.mark.asyncio
    async def test_static_meta_chain_task_name_stripped(self) -> None:
        """Assert _dispatch_chained_task strips chain_task_name from chained task's static meta."""
        main_task = _make_chain_task("main-task")
        chain_task = _make_chain_task("chain-task")
        chain_task.data = {"meta": {"target": "host1", "chain_task_name": "auto-next"}}
        parent_history = _make_chain_history(
            main_task,
            TaskHistoryStatusEnum.SUCCESS,
            {"chain_task_name": chain_task.name},
        )

        session_maker, _ = _make_chain_session_mock()

        with (
            patch(
                "app.tasks.celery.get_async_session_maker", return_value=session_maker
            ),
            patch(
                "app.tasks.celery.TaskManager.first", new_callable=AsyncMock
            ) as mock_task_first,
            patch(
                "app.tasks.celery.dispatch_queue_item", new_callable=AsyncMock
            ) as mock_dispatch,
        ):
            mock_task_first.return_value = chain_task
            mock_dispatch.return_value = AsyncMock()

            await _dispatch_chained_task(chain_task.name, parent_history)

        dispatched_history = mock_dispatch.call_args[0][0]
        assert "chain_task_name" not in dispatched_history.execution_request.meta

    @pytest.mark.asyncio
    async def test_unknown_task_logs_warning(self) -> None:
        """Assert _dispatch_chained_task logs a warning when task name is not found."""
        main_task = _make_chain_task("main-task")
        parent_history = _make_chain_history(
            main_task,
            TaskHistoryStatusEnum.SUCCESS,
            {"chain_task_name": "unknown-task"},
        )

        session_maker, _ = _make_chain_session_mock()

        with (
            patch(
                "app.tasks.celery.get_async_session_maker", return_value=session_maker
            ),
            patch(
                "app.tasks.celery.TaskManager.first", new_callable=AsyncMock
            ) as mock_task_first,
            patch(
                "app.tasks.celery.dispatch_queue_item", new_callable=AsyncMock
            ) as mock_dispatch,
            patch("app.tasks.celery.logger") as mock_logger,
        ):
            mock_task_first.return_value = None

            await _dispatch_chained_task("unknown-task", parent_history)

        mock_dispatch.assert_not_awaited()
        mock_logger.warning.assert_called_once()
        assert "unknown-task" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    async def test_max_depth_exceeded_no_dispatch(self) -> None:
        """Assert _dispatch_chained_task does not dispatch when chain depth limit is reached."""
        main_task = _make_chain_task("main-task")
        meta = {
            "chain_task_name": "chain-task",
            "chain_depth": _MAX_CHAIN_DEPTH,
        }
        parent_history = _make_chain_history(
            main_task, TaskHistoryStatusEnum.SUCCESS, meta
        )

        with (
            patch("app.tasks.celery.get_async_session_maker") as mock_session_maker,
            patch(
                "app.tasks.celery.dispatch_queue_item", new_callable=AsyncMock
            ) as mock_dispatch,
        ):
            await _dispatch_chained_task("chain-task", parent_history)

        mock_session_maker.assert_not_called()
        mock_dispatch.assert_not_awaited()


class TestSyncQueueItemChainDispatch:
    """Test chain dispatch behavior in sync_queue_item."""

    @pytest.mark.asyncio
    async def test_dispatches_chain_on_terminal_status(self) -> None:
        """Assert sync_queue_item dispatches the chained task when a running task completes."""
        main_task = _make_chain_task("main-task")
        chain_task = _make_chain_task("chain-task")

        running_history = _make_chain_history(
            main_task,
            TaskHistoryStatusEnum.RUNNING,
            {"chain_task_name": chain_task.name},
        )
        done_history = _make_chain_history(
            main_task,
            TaskHistoryStatusEnum.SUCCESS,
            {"chain_task_name": chain_task.name},
        )

        session_maker, _ = _make_chain_session_mock()

        with (
            patch(
                "app.tasks.celery.get_async_session_maker", return_value=session_maker
            ),
            patch(
                "app.tasks.celery.TaskHistoryManager.get_or_404",
                new_callable=AsyncMock,
                return_value=running_history,
            ),
            patch(
                "app.tasks.celery.TaskManager.get_root_task",
                new_callable=AsyncMock,
                return_value=main_task,
            ),
            patch("app.tasks.celery.get_executor_for_task") as mock_executor,
            patch(
                "app.tasks.celery.TaskHistoryManager.save",
                new_callable=AsyncMock,
                return_value=done_history,
            ),
            patch(
                "app.tasks.celery._dispatch_chained_task", new_callable=AsyncMock
            ) as mock_chain,
        ):
            executor = AsyncMock()
            executor.sync_task_history = AsyncMock(return_value=done_history)
            mock_executor.return_value = executor

            await sync_queue_item(1)

        mock_chain.assert_awaited_once_with(chain_task.name, done_history)

    @pytest.mark.asyncio
    async def test_no_chain_dispatch_when_still_running(self) -> None:
        """Assert sync_queue_item does not dispatch chain when task remains running."""
        main_task = _make_chain_task("main-task")
        chain_task = _make_chain_task("chain-task")

        running_history = _make_chain_history(
            main_task,
            TaskHistoryStatusEnum.RUNNING,
            {"chain_task_name": chain_task.name},
        )

        session_maker, _ = _make_chain_session_mock()

        with (
            patch(
                "app.tasks.celery.get_async_session_maker", return_value=session_maker
            ),
            patch(
                "app.tasks.celery.TaskHistoryManager.get_or_404",
                new_callable=AsyncMock,
                return_value=running_history,
            ),
            patch(
                "app.tasks.celery.TaskManager.get_root_task",
                new_callable=AsyncMock,
                return_value=main_task,
            ),
            patch("app.tasks.celery.get_executor_for_task") as mock_executor,
            patch(
                "app.tasks.celery.TaskHistoryManager.save",
                new_callable=AsyncMock,
                return_value=running_history,
            ),
            patch(
                "app.tasks.celery._dispatch_chained_task", new_callable=AsyncMock
            ) as mock_chain,
        ):
            executor = AsyncMock()
            executor.sync_task_history = AsyncMock(return_value=running_history)
            mock_executor.return_value = executor

            await sync_queue_item(1)

        mock_chain.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_chain_dispatch_when_task_failed(self) -> None:
        """Assert sync_queue_item does not dispatch chain when the task fails."""
        main_task = _make_chain_task("main-task")
        chain_task = _make_chain_task("chain-task")

        running_history = _make_chain_history(
            main_task,
            TaskHistoryStatusEnum.RUNNING,
            {"chain_task_name": chain_task.name},
        )
        failed_history = _make_chain_history(
            main_task,
            TaskHistoryStatusEnum.FAILED,
            {"chain_task_name": chain_task.name},
        )

        session_maker, _ = _make_chain_session_mock()

        with (
            patch(
                "app.tasks.celery.get_async_session_maker", return_value=session_maker
            ),
            patch(
                "app.tasks.celery.TaskHistoryManager.get_or_404",
                new_callable=AsyncMock,
                return_value=running_history,
            ),
            patch(
                "app.tasks.celery.TaskManager.get_root_task",
                new_callable=AsyncMock,
                return_value=main_task,
            ),
            patch("app.tasks.celery.get_executor_for_task") as mock_executor,
            patch(
                "app.tasks.celery.TaskHistoryManager.save",
                new_callable=AsyncMock,
                return_value=failed_history,
            ),
            patch(
                "app.tasks.celery._dispatch_chained_task", new_callable=AsyncMock
            ) as mock_chain,
        ):
            executor = AsyncMock()
            executor.sync_task_history = AsyncMock(return_value=failed_history)
            mock_executor.return_value = executor

            await sync_queue_item(1)

        mock_chain.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_chain_dispatch_when_no_chain_task_name(self) -> None:
        """Assert sync_queue_item does not dispatch chain when chain_task_name is absent."""
        main_task = _make_chain_task("main-task")

        running_history = _make_chain_history(
            main_task,
            TaskHistoryStatusEnum.RUNNING,
            {},
        )
        done_history = _make_chain_history(
            main_task,
            TaskHistoryStatusEnum.SUCCESS,
            {},
        )

        session_maker, _ = _make_chain_session_mock()

        with (
            patch(
                "app.tasks.celery.get_async_session_maker", return_value=session_maker
            ),
            patch(
                "app.tasks.celery.TaskHistoryManager.get_or_404",
                new_callable=AsyncMock,
                return_value=running_history,
            ),
            patch(
                "app.tasks.celery.TaskManager.get_root_task",
                new_callable=AsyncMock,
                return_value=main_task,
            ),
            patch("app.tasks.celery.get_executor_for_task") as mock_executor,
            patch(
                "app.tasks.celery.TaskHistoryManager.save",
                new_callable=AsyncMock,
                return_value=done_history,
            ),
            patch(
                "app.tasks.celery._dispatch_chained_task", new_callable=AsyncMock
            ) as mock_chain,
        ):
            executor = AsyncMock()
            executor.sync_task_history = AsyncMock(return_value=done_history)
            mock_executor.return_value = executor

            await sync_queue_item(1)

        mock_chain.assert_not_awaited()
