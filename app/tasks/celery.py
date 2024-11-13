"""Module for executing and triggering Celery tasks.

This module defines functions for executing tasks asynchronously via Celery,
along with utility functions to process queue items.
"""

import logging
from typing import Any

from asgiref.sync import async_to_sync
from celery import Task
from fastapi.encoders import jsonable_encoder
from pydantic import validate_call

from app.core.celery.utils import create_celery
from app.core.exceptions import HTTPBadRequestException, HTTPConflictException
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import create_task_history, get_executor, get_task_by_name
from app.tasks.models import (
    TaskBackendEnum,
    TaskExecuteRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
)

logger = logging.getLogger(__name__)

celery = create_celery("tasks")


@celery.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def execute_task_queue(self: Task, queue_id: int) -> dict[str, Any]:
    """Trigger a Celery task by executing a queue item.

    :param self: The Celery task instance.
    :type self: Task
    :param queue_id: The ID of the queue item to trigger.
    :type queue_id: int
    :return: The data of the processed TaskHistory.
    :rtype: dict[str, Any]
    """
    logger.info("Executing task with queue_id: %s", queue_id)
    return jsonable_encoder(async_to_sync(process_queue_item)(queue_id))


@celery.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def execute_task_by_name(
    self: Task, task_name: str, execution_data: TaskExecuteRequest | None = None
) -> dict[str, Any]:
    """Define Celery task to execute a SEP task by name.

    :param self: The Celery task instance.
    :type self: Task
    :param task_name: The name of the task to execute.
    :type task_name: int | None
    :param execution_data: Execution details and parameters, if any.
    :type execution_data: TaskExecuteRequest | None
    :return: The data of the processed TaskHistory.
    :rtype: dict[str, Any]
    """
    task_history = async_to_sync(prepare_task_history)(task_name, execution_data)
    return jsonable_encoder(async_to_sync(process_queue_item)(task_history.id))


@validate_call
async def prepare_task_history(
    task_name: str, execution_data: TaskExecuteRequest | None = None
) -> TaskHistory:
    """Prepare and record the history of a task execution request.

    :param task_name: The name of the task to execute.
    :type task_name: str
    :param execution_data: Execution details and parameters, if any.
    :type execution_data: TaskExecuteRequest | None
    :return: The logged TaskHistory entry.
    :rtype: TaskHistory
    """
    if execution_data is not None:
        execution_data.eta = None
    async_session = get_async_session_maker()
    async with async_session() as session:
        task = await get_task_by_name(session, task_name)
        return await create_task_history(session, task, execution_data)


async def process_queue_item(queue_id: int) -> TaskHistory:
    """Process an item from the history table.

    :param queue_id: The unique identifier of the queue item to process.
    :type queue_id: int
    :return: The TaskHistory object post execution.
    :rtype: TaskHistory
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
            raise HTTPConflictException("Queue item is not in a pending state.")

        if task.backend == TaskBackendEnum.PROXY:
            task = await TaskManager.retrieve_by_name(
                session=session, name=task.data["task"]
            )

        match task.backend:
            case TaskBackendEnum.NOMAD:
                executor = get_executor()
            case _:
                raise HTTPBadRequestException("Unsupported task backend.")
        return await executor.run(session, queue_item, task)
