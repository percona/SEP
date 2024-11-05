"""Provide utility functions for processing task queue items."""

import logging
from collections.abc import Awaitable
from http import HTTPStatus

from fastapi import BackgroundTasks, HTTPException

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.exceptions import HTTPBadRequestException
from app.tasks.config import tasks_settings
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import get_executor
from app.tasks.models import (
    TaskBackendEnum,
    TaskExecuteRequest,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
)

logger = logging.getLogger(__name__)


async def process_queue_item(queue_id: int) -> None:
    """Process an item from the history table.

    :param queue_id: The unique identifier of the queue item to process.
    :type queue_id: int
    :raises HTTPException: If the queue item status is not PENDING,
        raises a 409 Conflict error.
    :raises HTTPBadRequestException: If the task backend is unsupported,
        raises a 400 Bad Request error.
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        queue_item = await TaskHistoryManager.get_or_404(
            session,
            select_related=[TaskHistory.task],
            id=queue_id,
        )
        task = queue_item.task

        if queue_item.status != TaskHistoryStatusEnum.PENDING:
            raise HTTPException(
                status_code=HTTPStatus.CONFLICT,
                detail="Queue item is not in a pending state.",
            )

        if task.backend == TaskBackendEnum.PROXY:
            task = await TaskManager.retrieve_by_name(
                session=session, name=task.data["task"]
            )

        match task.backend:
            case TaskBackendEnum.NOMAD:
                executor = get_executor()
            case _:
                raise HTTPBadRequestException("Unsupported task backend.")
        await executor.run(session, queue_item, task)


async def prepare_task_history(
    task_name: str, execution_data: TaskExecuteRequest = None
) -> Awaitable[TaskHistory]:
    """Prepare and record the history of a task execution request."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        execution_data = (
            TaskExecuteRequest() if execution_data is None else execution_data
        )
        logger.debug("Executing task %s", task_name)
        config = await TaskManager.retrieve_by_name(session=session, name=task_name)
        if config.is_template:
            raise HTTPForbiddenException(
                f"Task {task_name} is a template and cannot be executed",
            )
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


async def schedule_queue_item(
    history_recorded: TaskHistory,
    background_tasks: BackgroundTasks,
) -> dict[str, TaskHistory]:
    """Schedule queue item to execution."""
    # Check how to proceed with execution
    mode = tasks_settings.EXECUTE_MODE
    match mode:
        case "background":
            background_tasks.add_task(
                process_queue_item,
                queue_id=history_recorded.id,
            )
        case _:
            logger.critical("Unknown execution mode '%s'", mode)
            raise HTTPException(status_code=HTTPStatus.EXPECTATION_FAILED)
    return {"task_history_id": history_recorded}
