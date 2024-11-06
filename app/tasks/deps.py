"""Define dependencies for the Tasks API."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.config import tasks_settings
from app.tasks.crud import TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    Task,
    TaskBackendEnum,
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


async def get_config(task_name: str) -> Task:
    """Get Task object by task name for checking it is template or not.

    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :return: The Task object associated with the provided name.
    :rtype: Task
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        return await TaskManager.retrieve_by_name(session=session, name=task_name)


TaskConfig = Annotated[Task, Depends(get_config)]
