"""Define tests for app.tasks.celery module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.celery import _dispatch_chained_task, _MAX_CHAIN_DEPTH, sync_queue_item
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
)
from tests.app.factories import TaskFactory


def _make_history(task: Task, status: TaskHistoryStatusEnum, meta: dict) -> TaskHistory:
    """Build an in-memory TaskHistory without persisting it."""
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


def _make_task(name: str) -> Task:
    """Build an in-memory Task without persisting it."""
    return TaskFactory.build(
        name=name,
        backend=TaskBackendEnum.NOMAD,
        data={"meta": {"target": "host1"}},
    )


def _make_session_mock() -> tuple[MagicMock, AsyncMock]:
    """Return (session_maker_mock, session_mock) for patching get_async_session_maker."""
    session_mock = AsyncMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    session_maker = MagicMock()
    session_maker.return_value = session_mock
    return session_maker, session_mock


@pytest.mark.asyncio
async def test_dispatch_chained_task_dispatches_on_success() -> None:
    """Test that _dispatch_chained_task dispatches the chained task when found."""
    main_task = _make_task("main-task")
    chain_task = _make_task("chain-task")
    parent_history = _make_history(
        main_task, TaskHistoryStatusEnum.SUCCESS, {"chain_task_name": chain_task.name}
    )

    session_maker, _ = _make_session_mock()

    with (
        patch("app.tasks.celery.get_async_session_maker", return_value=session_maker),
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
async def test_dispatch_chained_task_unknown_task_logs_warning() -> None:
    """Test that _dispatch_chained_task logs a warning when task name is not found."""
    main_task = _make_task("main-task")
    parent_history = _make_history(
        main_task, TaskHistoryStatusEnum.SUCCESS, {"chain_task_name": "unknown-task"}
    )

    session_maker, _ = _make_session_mock()

    with (
        patch("app.tasks.celery.get_async_session_maker", return_value=session_maker),
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
async def test_dispatch_chained_task_max_depth_exceeded_no_dispatch() -> None:
    """Test that _dispatch_chained_task does not dispatch when chain depth limit is reached."""
    main_task = _make_task("main-task")
    meta = {
        "chain_task_name": "chain-task",
        "chain_depth": _MAX_CHAIN_DEPTH,
    }
    parent_history = _make_history(main_task, TaskHistoryStatusEnum.SUCCESS, meta)

    with (
        patch("app.tasks.celery.get_async_session_maker"),
        patch(
            "app.tasks.celery.dispatch_queue_item", new_callable=AsyncMock
        ) as mock_dispatch,
    ):
        await _dispatch_chained_task("chain-task", parent_history)

    mock_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_queue_item_dispatches_chain_on_terminal_status() -> None:
    """Test that sync_queue_item dispatches the chained task when a running task completes."""
    main_task = _make_task("main-task")
    chain_task = _make_task("chain-task")

    running_history = _make_history(
        main_task,
        TaskHistoryStatusEnum.RUNNING,
        {"chain_task_name": chain_task.name},
    )
    done_history = _make_history(
        main_task,
        TaskHistoryStatusEnum.SUCCESS,
        {"chain_task_name": chain_task.name},
    )

    session_maker, _ = _make_session_mock()

    with (
        patch("app.tasks.celery.get_async_session_maker", return_value=session_maker),
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
async def test_sync_queue_item_no_chain_dispatch_when_still_running() -> None:
    """Test that sync_queue_item does not dispatch chain when task remains running."""
    main_task = _make_task("main-task")
    chain_task = _make_task("chain-task")

    running_history = _make_history(
        main_task,
        TaskHistoryStatusEnum.RUNNING,
        {"chain_task_name": chain_task.name},
    )

    session_maker, _ = _make_session_mock()

    with (
        patch("app.tasks.celery.get_async_session_maker", return_value=session_maker),
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
async def test_sync_queue_item_no_chain_dispatch_when_task_failed() -> None:
    """Test that sync_queue_item does not dispatch chain when the task fails."""
    main_task = _make_task("main-task")
    chain_task = _make_task("chain-task")

    running_history = _make_history(
        main_task,
        TaskHistoryStatusEnum.RUNNING,
        {"chain_task_name": chain_task.name},
    )
    failed_history = _make_history(
        main_task,
        TaskHistoryStatusEnum.FAILED,
        {"chain_task_name": chain_task.name},
    )

    session_maker, _ = _make_session_mock()

    with (
        patch("app.tasks.celery.get_async_session_maker", return_value=session_maker),
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
async def test_sync_queue_item_no_chain_dispatch_when_no_chain_task_name() -> None:
    """Test that sync_queue_item does not dispatch chain when chain_task_name is absent."""
    main_task = _make_task("main-task")

    running_history = _make_history(
        main_task,
        TaskHistoryStatusEnum.RUNNING,
        {},
    )
    done_history = _make_history(
        main_task,
        TaskHistoryStatusEnum.SUCCESS,
        {},
    )

    session_maker, _ = _make_session_mock()

    with (
        patch("app.tasks.celery.get_async_session_maker", return_value=session_maker),
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
