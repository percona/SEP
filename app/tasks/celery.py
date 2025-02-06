"""Define Celery tasks and utilities for the Tasks app.

This module defines functions for executing tasks asynchronously via Celery,
along with utility functions to process queue items.
"""

import logging
from typing import Any

from asgiref.sync import async_to_sync
from celery import Task
from fastapi.encoders import jsonable_encoder

from app.core.celery.db import get_async_session_maker as get_celery_async_session_maker
from app.core.celery.utils import create_celery
from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
)
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import create_task_history, get_executor, get_task_by_name
from app.tasks.models import (
    TaskBackendEnum,
    TaskHistory,
    TaskHistoryStatusEnum,
)
from app.tasks.periodic.config import periodic_tasks_settings, PeriodicTaskAction
from app.tasks.periodic.crud import PeriodicTaskManager
from app.tasks.periodic.models import PeriodicTaskExecuteRequest

logger = logging.getLogger(__name__)

celery = create_celery("tasks")


@celery.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": celery.conf.max_retries},
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
    retry_kwargs={"max_retries": celery.conf.max_retries},
)
def execute_task_by_name(
    self: Task, task_name: str, execution_data: PeriodicTaskExecuteRequest | None = None
) -> dict[str, Any]:
    """Define Celery task to execute a SEP task by name.

    :param self: The Celery task instance.
    :type self: Task
    :param task_name: The name of the task to execute.
    :type task_name: int | None
    :param execution_data: Execution details and parameters, if any.
    :type execution_data: PeriodicTaskExecuteRequest | None
    :return: The data of the processed TaskHistory.
    :rtype: dict[str, Any]
    """
    task_history = async_to_sync(prepare_periodic_task_history)(
        task_name, execution_data
    )
    return jsonable_encoder(async_to_sync(process_queue_item)(task_history.id))


@celery.task
def process_expired_and_orphaned_periodic_tasks() -> None:
    """Define Celery task to process expired and orphaned periodic tasks."""
    async_to_sync(process_expired_periodic_tasks)()
    async_to_sync(process_orphaned_periodic_tasks)()


async def process_expired_periodic_tasks() -> None:
    """Find and process expired periodic tasks."""
    logger.debug("Processing expired tasks...")
    celery_beat_async_session = get_celery_async_session_maker(create_new_engine=True)
    async with celery_beat_async_session() as celery_beat_session:
        await PeriodicTaskManager.process_expired(celery_beat_session)


async def process_orphaned_periodic_tasks() -> None:
    """Find and process orphaned periodic tasks."""
    action = periodic_tasks_settings.ON_ORPHAN
    if action == PeriodicTaskAction.NOTHING:
        logger.debug("ON_ORPHAN is NOTHING, ignoring orphaned periodic tasks")
        return

    async_session = get_async_session_maker(create_new_engine=True)
    async with async_session() as session:
        task_names = [task.name for task in await TaskManager.list_active(session)]

    celery_beat_async_session = get_celery_async_session_maker(create_new_engine=True)
    async with celery_beat_async_session() as celery_beat_session:
        await PeriodicTaskManager.perform_action_where(
            celery_beat_session,
            action,
            ~PeriodicTaskManager.build_where_clause_by_task_names(*task_names),
        )


async def prepare_periodic_task_history(
    task_name: str, execution_data: PeriodicTaskExecuteRequest | None = None
) -> TaskHistory:
    """Prepare and record the history of a periodic task execution request.

    :param task_name: The name of the task to execute.
    :type task_name: str
    :param execution_data: Execution details and parameters, if any.
    :type execution_data: PeriodicTaskExecuteRequest | None
    :return: The logged TaskHistory entry.
    :rtype: TaskHistory
    """
    execution_data = (
        PeriodicTaskExecuteRequest.model_validate(execution_data)
        if execution_data
        else None
    )
    async_session = get_async_session_maker(create_new_engine=True)
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
    async_session = get_async_session_maker(create_new_engine=True)
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
