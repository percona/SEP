"""Define dependencies for the Tasks API."""

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPNotFoundException
from app.tasks.config import tasks_settings
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    GeneratedTask,
    Task,
    TaskBackendEnum,
    TaskExecuteRequest,
    TaskExecutionRequest,
    TaskGroup,
    TaskGroupTask,
    TaskGroupTaskTemplate,
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


async def get_task_by_name(session: SessionDep, task_name: str) -> Task:
    """Get Task object by task name.

    :param session: The asynchronous database session.
    :type session: AsyncSession
    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :return: The retrieved Task object.
    :rtype: Task
    """
    logger.debug("Requesting task %s", task_name)
    return await TaskManager.retrieve_by_name(session=session, name=task_name)


TaskDep = Annotated[Task, Depends(get_task_by_name)]


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
        session=session, name=task_name, is_template=False
    )


ExecutableTaskDep = Annotated[Task, Depends(get_executable_task_by_name)]


async def create_task_history(
    session: SessionDep,
    task: ExecutableTaskDep,
    execution_data: TaskExecuteRequest | None = None,
) -> TaskHistory:
    """Prepare and record the history of a task execution request.

    :param session: The asynchronous database session.
    :type session: AsyncSession
    :param task: The task to execute.
    :type task: Task
    :param execution_data: Execution details and parameters, if any.
    :type execution_data: TaskExecuteRequest | None
    :return: The logged TaskHistory entry.
    :rtype: TaskHistory
    """
    logger.debug("Creating TaskHistory for  %s", task.name)
    execution_data = TaskExecuteRequest() if execution_data is None else execution_data
    if task.backend == TaskBackendEnum.PROXY:
        execution_data.meta |= task.data.get("meta", {})
        execution_data.payload = task.data.get("payload", execution_data.payload)
    task_history = TaskHistory(
        task_id=task.id,
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
    return await TaskHistoryManager.save(session, task_history)


CreatedTaskHistory = Annotated[TaskHistory, Depends(create_task_history)]


async def serialize_generated_task(
    session: SessionDep,
    generated_task: GeneratedTask,
    executor: TaskExecutor,
    task: Task | None = None,
) -> Task:
    """Serialize and validate a generated task payload.

    If `task` is None, create a new Task from the template.
    Otherwise, update the existing task.
    """
    # Retrieve the template task
    template = await TaskManager.retrieve_by_name(
        session=session,
        name=f"generic-nomad-{generated_task.template}",
        is_template=True,
    )
    if not template:
        raise HTTPNotFoundException("Template not found")

    if task is None:
        # For a new task, create it from scratch
        task = Task(
            name=generated_task.name,
            owner=generated_task.app,
            backend=template.backend,
            data=template.data.copy(),  # copy to avoid unwanted mutation
        )
    else:
        # For updating an existing task, update its backend and data
        task.name = generated_task.name
        task.backend = template.backend
        task.data = template.data.copy()

    tpl = task.data

    # Build the TaskGroup payload from the generated commands
    tg = TaskGroup(
        engine=task.backend.name,
        name="execution",
        tasks=[],
        parallel=generated_task.parallel and len(generated_task.commands) > 1,
    )
    for i, cmd in enumerate(generated_task.commands):
        templates = [
            TaskGroupTaskTemplate(**config) for config in cmd.get("config", [])
        ]
        tg.tasks.append(
            TaskGroupTask(
                name=f"step{i + 1}" if not cmd.get("name") else cmd["name"],
                config={"args": cmd.get("args"), "command": cmd.get("command")},
                meta=cmd.get("meta", {}),
                templates=templates,
            )
        )
    tpl.update(tg.to_payload())

    # Handle periodic scheduling if present in the payload
    if "Periodic" in tpl:
        if generated_task.schedule and not generated_task.schedule.get("save_only"):
            tpl["Periodic"] = generated_task.schedule
        else:
            del tpl["Periodic"]

    # Adjust constraints for NOMAD backend if needed
    if task.backend == TaskBackendEnum.NOMAD:
        if tpl.get("Type") == "batch":
            if generated_task.target in ["all", "*"]:
                tpl["Constraints"][0]["RTarget"] = ".*"
                tpl["Constraints"][0]["Operand"] = "regexp"
            else:
                tpl["Constraints"][0]["RTarget"] = generated_task.target
                tpl["Constraints"][0]["Operand"] = "="
        # Validate the job via the executor
        task.data = await executor.validate_job(tpl)
    else:
        raise NotImplementedError(f"{task.backend} is currently unsupported")

    logger.debug("Serialized generated task %s", task.name)
    return task


async def prepare_new_generated_task(
    session: SessionDep,
    generated_task: GeneratedTask,
    executor: TaskExecutor,
) -> Task:
    """Dependency to prepare a new generated task."""
    return await serialize_generated_task(session, generated_task, executor, task=None)


PreparedNewGeneratedTask = Annotated[Task, Depends(prepare_new_generated_task)]


async def prepare_existing_generated_task(
    session: SessionDep,
    generated_task: GeneratedTask,
    executor: TaskExecutor,
    task: TaskDep,
) -> Task:
    """Dependency to prepare an existing generated task for update."""
    return await serialize_generated_task(session, generated_task, executor, task=task)


PreparedExistingGeneratedTask = Annotated[
    Task, Depends(prepare_existing_generated_task)
]
