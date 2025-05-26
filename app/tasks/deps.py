"""Define dependencies for the Tasks API."""

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.config import tasks_settings
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskExecuteRequest,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
)

logger = logging.getLogger(__name__)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an asynchronous database session for FastAPI routes.

    This function provides a dependency for FastAPI routes that yields an `AsyncSession`
    for interacting with the database. The session is properly closed after use.

    :yield: An asynchronous session for database operations.
    :rtype: AsyncGenerator[AsyncSession, None]
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_executor(backend: TaskBackendEnum = TaskBackendEnum.NOMAD) -> BaseExecutor:
    """Get the task executor.

    :return: The task executor.
    :rtype: BaseExecutor
    """
    # TODO: Allow other executors  # noqa: TD002, TD003
    if backend == TaskBackendEnum.NOMAD:
        return tasks_settings.NOMAD
    raise ValueError(f"Unsupported backend {backend}")


TaskExecutor = Annotated[BaseExecutor, Depends(get_executor)]


async def get_active_task_by_name(session: SessionDep, task_name: str) -> Task:
    """Get an active (not deleted) Task object by task name.

    :param session: The asynchronous database session.
    :type session: AsyncSession
    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :return: The retrieved Task object.
    :rtype: Task
    """
    logger.debug("Requesting task %s", task_name)
    return await TaskManager.retrieve_by_name(
        session=session, name=task_name, is_active=True
    )


TaskDep = Annotated[Task, Depends(get_active_task_by_name)]


async def get_executable_task_by_name(session: SessionDep, task_name: str) -> Task:
    """Get non-template Task object by task name.

    :param session: The asynchronous database session.
    :type session: AsyncSession
    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :return: The Task object if valid.
    :rtype: Task
    """
    logger.debug("Requesting executable task %s", task_name)
    return await TaskManager.retrieve_by_name(
        session=session, name=task_name, is_template=False, is_active=True
    )


ExecutableTaskDep = Annotated[Task, Depends(get_executable_task_by_name)]


def prepare_task_history(
    task: ExecutableTaskDep,
    execution_data: TaskExecuteRequest | None = None,
) -> TaskHistory:
    """Prepare the history of a task execution request.

    :param task: The task to execute.
    :type task: Task
    :param execution_data: Execution details and parameters, if any.
    :type execution_data: TaskExecuteRequest | None
    :return: The logged TaskHistory entry.
    :rtype: TaskHistory
    """
    logger.debug("Preparing TaskHistory for %s", task.name)
    execution_data = TaskExecuteRequest() if execution_data is None else execution_data
    if task.backend == TaskBackendEnum.PROXY:
        execution_data.meta |= task.data.get("meta", {})
        execution_data.payload = task.data.get("payload", execution_data.payload)
    return TaskHistory(
        task_id=task.id,
        task=task,
        execution_request=TaskExecutionRequest(
            task=task.name,
            target=execution_data.meta.get("target", "all"),
            meta=execution_data.meta,
            payload=execution_data.payload,
            tracking={"evaluation_id": ""},
            eta=execution_data.eta,
        ),
        status=TaskHistoryStatusEnum.PENDING,
    )


PreparedTaskHistory = Annotated[TaskHistory, Depends(prepare_task_history)]


async def create_task_history(
    session: SessionDep,
    task_history: PreparedTaskHistory,
) -> TaskHistory:
    """Record a prepared history of a task execution request.

    :param session: The asynchronous database session.
    :type session: AsyncSession
    :param task_history: The task history to record.
    :type task_history: PreparedTaskHistory
    :return: The logged TaskHistory entry.
    :rtype: TaskHistory
    """
    return await TaskHistoryManager.save(session, task_history)


CreatedTaskHistory = Annotated[TaskHistory, Depends(create_task_history)]


async def get_task_history(
    session: SessionDep,
    task_history_id: int,
) -> TaskHistory:
    """Get TaskHistory object by task history ID.

    :param session: The asynchronous database session.
    :type session: AsyncSession
    :param task_history_id: The ID of the task history to retrieve.
    :type task_history_id: int
    :return: The retrieved TaskHistory object.
    :rtype: TaskHistory
    """
    logger.debug("Requesting task history %s", task_history_id)
    return await TaskHistoryManager.get_or_404(session=session, id=task_history_id)


TaskHistoryDep = Annotated[TaskHistory, Depends(get_task_history)]


async def get_task_history_with_task(
    session: SessionDep,
    task_history_id: int,
) -> TaskHistory:
    """Get TaskHistory object by task history ID with related task.

    :param session: The asynchronous database session.
    :type session: AsyncSession
    :param task_history_id: The ID of the task history to retrieve.
    :type task_history_id: int
    :return: The retrieved TaskHistory object.
    :rtype: TaskHistory
    """
    logger.debug("Requesting task history %s", task_history_id)
    return await TaskHistoryManager.get_or_404(
        session=session, select_related=(TaskHistory.task,), id=task_history_id
    )


TaskHistoryWithTaskDep = Annotated[TaskHistory, Depends(get_task_history_with_task)]
