"""Define dependencies for the Tasks API."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth.exceptions import HTTPForbiddenException
from app.tasks.config import tasks_settings
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    TaskBackendEnum,
    TaskExecuteRequest,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
)


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


async def prepare_task_history(
    session: SessionDep,
    task_name: str,
    execution_data: TaskExecuteRequest = None,
) -> TaskHistory:
    """Retrieve task configuration and create a history record for task execution.

    :param session: Database session dependency.
    :param task_name: Name of the task to retrieve and execute.
    :param execution_data: Optional execution data for the task.
    :return: Saved task history record.
    :raises HTTPForbiddenException: If the task is a template and cannot be executed.
    """
    config = await TaskManager.retrieve_by_name(session=session, name=task_name)
    if config.is_template:
        raise HTTPForbiddenException(
            f"Task {task_name} is a template and cannot be executed",
        )
    execution_data = TaskExecuteRequest() if execution_data is None else execution_data
    if config.backend == TaskBackendEnum.PROXY:
        execution_data.meta |= config.data.get("meta", {})
        execution_data.payload = config.data.get("payload", execution_data.payload)
    # Record the task execution request
    task_history = TaskHistory(
        task_id=config.id,
        execution_request=TaskExecutionRequest(
            task=task_name,
            target=execution_data.meta.get("target", "all"),
            meta=execution_data.meta,
            payload=execution_data.payload,
            tracking={"evaluation_id": ""},
        ),
        status=TaskHistoryStatusEnum.PENDING,
    )
    return await TaskHistoryManager.save(session, task_history)


TaskHistoryDep = Annotated[TaskHistory, Depends(prepare_task_history)]
