"""Module contains utility functions for processing task queue items."""

from collections.abc import Awaitable
from http import HTTPStatus
import logging
from fastapi import BackgroundTasks, HTTPException

from app.core.auth.exceptions import HTTPForbiddenException
from app.tasks.crud import PeriodicTaskManager, TaskHistoryManager, TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import get_executor
from app.tasks.config import tasks_settings
from app.tasks.models import TaskBackendEnum, TaskExecuteRequest, TaskExecutionRequest, TaskHistory, TaskHistoryStatusEnum
import pdb

logger = logging.getLogger(__name__)


async def process_queue_item(queue_id: int) -> None:
    """Process an item from the history table."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        queue_item = await TaskHistoryManager.get_or_404(
            session,
            select_related=[TaskHistory.task],
            id=queue_id,
        )
        task = queue_item.task

        if queue_item.status != TaskHistoryStatusEnum.PENDING:
            raise HTTPException(status_code=HTTPStatus.EXPECTATION_FAILED)

        match task.backend:
            case TaskBackendEnum.NOMAD:
                executor = get_executor()
            case _:
                raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)

        await executor.run(session, queue_item)
         

async def prepare_task_history(
    task_name: str, execution_data: TaskExecuteRequest = None
) -> Awaitable[TaskHistory]:
    async_session = get_async_session_maker()
    async with async_session() as session:
        execution_data = TaskExecuteRequest() if execution_data is None else execution_data
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
