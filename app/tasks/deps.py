"""Define dependencies for the Tasks API."""

import logging
from collections import defaultdict
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import Request

from app.tasks.anonymizer import encode_selection
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
    TaskOwner,
    TaskWrite,
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
    if task.owner == TaskOwner.ALTERS:
        target = task.data["Constraints"][0]["RTarget"]
    else:
        target = execution_data.meta.get("target")
    if not target:
        raise ValueError("Execution target is required in execution data meta.")

    return TaskHistory(
        task_id=task.id,
        task=task,
        execution_request=TaskExecutionRequest(
            task=task.name,
            target=target,
            meta=execution_data.meta,
            payload=execution_data.payload,
            tracking={"evaluation_id": ""},
            eta=execution_data.eta,
        ),
        status=TaskHistoryStatusEnum.PENDING,
    )


PreparedTaskHistory = Annotated[TaskHistory, Depends(prepare_task_history)]


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


async def get_task_with_anonymized_value(task: TaskWrite) -> TaskWrite:
    """Add anonymization configuration to a task based on its owner.

    :param task: The task write model to anonymize.
    :type task: TaskWrite
    :return: The task with anonymization configuration added.
    :rtype: TaskWrite
    """
    task.anonymize = encode_selection(tasks_settings.MASKING_ENTITIES[task.owner])
    return task


TaskWriteWithAnonymizeDep = Annotated[
    TaskWrite, Depends(get_task_with_anonymized_value)
]


def get_logs_offsets(request: Request) -> defaultdict[str, dict[str, int]]:
    """Extract log offsets from the request query parameters.

    This function looks for query parameters that end with "_offset" and extracts
    the step and log type from the parameter name. It returns a dictionary where
    the keys are steps and the values are dictionaries mapping log types to their
    corresponding offsets.

    :param request: The FastAPI request object containing query parameters.
    :type request: Request
    :return: A dictionary mapping steps to log types and their offsets.
    :rtype: defaultdict[str, dict[str, int]]
    """
    offsets = defaultdict(dict)
    for raw_key, raw_val in request.query_params.items():
        if raw_key.endswith("_offset"):
            try:
                step, log_type, _ = raw_key.rsplit("_", 2)
                offsets[step][log_type] = max(0, int(raw_val))
            except ValueError:
                continue
    return offsets
