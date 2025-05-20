"""Define Celery tasks and utilities for the Tasks app.

This module defines functions for executing tasks asynchronously via Celery,
along with utility functions to process queue items.
"""

import logging
from typing import Any

from asgiref.sync import async_to_sync
from celery import Task
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func
from sqlmodel import col, or_

from app.core.celery.utils import create_celery
from app.core.db.utils import func_json_extract
from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
)
from app.core.utils import utc_now
from app.tasks.config import tasks_settings
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import (
    get_executor,
    get_task_by_name,
    prepare_task_history,
)
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    TaskHistory,
    TaskHistoryStatusEnum,
)
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
    queue_item = async_to_sync(get_task_history)(queue_id)
    return jsonable_encoder(async_to_sync(dispatch_queue_item)(queue_item))


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
    return jsonable_encoder(async_to_sync(dispatch_queue_item)(task_history))


@celery.task
def sync_running_tasks() -> None:
    """Define Celery task to sync running tasks."""
    async_to_sync(sync_running_items)()


@celery.task
def sync_task_history(task_history_id: int) -> None:
    """Define Celery task to sync a task history item.

    :param task_history_id: The unique identifier of the task history item to sync.
    :type task_history_id: int
    """
    logger.debug("Syncing task history %s", task_history_id)
    async_to_sync(sync_queue_item)(task_history_id)
    logger.debug("Finished syncing task history %s", task_history_id)


async def get_task_history(queue_id: int) -> TaskHistory:
    """Get TaskHistory object by queue ID.

    :param queue_id: The unique identifier of the queue item to retrieve.
    :type queue_id: int
    :return: The TaskHistory object.
    :rtype: TaskHistory
    """
    async_session = get_async_session_maker(create_new_engine=True)
    async with async_session() as session:
        return await TaskHistoryManager.get_or_404(
            session, select_related=[TaskHistory.task], id=queue_id
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
        return prepare_task_history(task, execution_data)


async def dispatch_queue_item(queue_item: TaskHistory) -> TaskHistory:
    """Process an item from the history table.

    :param queue_item: The TaskHistory object to dispatch.
    :type queue_item: TaskHistory
    :return: The TaskHistory object post execution.
    :rtype: TaskHistory
    :raises HTTPException: If the queue item status is not PENDING,
        raises a 409 Conflict error.
    :raises HTTPBadRequestException: If the task backend is unsupported,
        raises a 400 Bad Request error.
    """
    async_session = get_async_session_maker(create_new_engine=True)
    async with async_session() as session:
        engine_name = session.get_bind().name
        if queue_item.status != TaskHistoryStatusEnum.PENDING:
            raise HTTPConflictException("Queue item is not in a pending state.")
        meta_where_clauses = []
        if queue_item.execution_request.meta:
            meta_where_clauses = [
                func_json_extract(
                    engine_name, TaskHistory.execution_request, "meta", field
                )
                == value
                for field, value in queue_item.execution_request.meta.items()
            ]
        if identical_task := (
            await TaskHistoryManager.first(
                session,
                func_json_extract(engine_name, TaskHistory.execution_request, "task")
                == queue_item.execution_request.task,
                func_json_extract(engine_name, TaskHistory.execution_request, "target")
                == queue_item.execution_request.target,
                func_json_extract(engine_name, TaskHistory.execution_request, "payload")
                == queue_item.execution_request.payload,
                *meta_where_clauses,
                col(TaskHistory.status).in_(
                    [TaskHistoryStatusEnum.PENDING, TaskHistoryStatusEnum.RUNNING]
                ),
                col(TaskHistory.id) != queue_item.id,
                task_id=queue_item.task_id,
            )
        ):
            raise HTTPConflictException(
                f"Identical queue item already running ({identical_task.id})."
            )
        task = await TaskManager.get_root_task(session, queue_item.task)
        executor = get_executor_for_task(task)
        return await executor.dispatch_task(session, queue_item, task)


async def sync_running_items() -> None:
    """Sync running tasks in the task history.

    This function updates the `sync_in_progress_started_at` field for tasks that are
    either not currently in progress or have been in progress for longer than the
    configured SYNC_LOCK_TTL. It then dispatches the sync task for those tasks.
    """
    async_session = get_async_session_maker(create_new_engine=True)
    async with async_session() as session:
        result = await TaskHistoryManager.update_where(
            session,
            {"sync_in_progress_started_at": func.now()},
            or_(
                col(TaskHistory.sync_in_progress_started_at).is_(None),
                col(TaskHistory.sync_in_progress_started_at)
                < (utc_now() - tasks_settings.SYNC_LOCK_TTL),
            ),
            returning=("id",),
            status=TaskHistoryStatusEnum.RUNNING,
        )
        args = [(item_id,) for item_id in result.scalars().all()]
        if args:
            logger.debug("Dispatching sync of %d running tasks", len(args))
            chunk_size = 100
            sync_task_history.chunks(args, chunk_size).apply_async()


async def sync_queue_item(queue_id: int) -> TaskHistory:
    """Sync a task history item.

    :param queue_id: The unique identifier of the queue item to sync.
    :type queue_id: int
    :return: The TaskHistory object post sync.
    :rtype: TaskHistory
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
        if queue_item.status == TaskHistoryStatusEnum.RUNNING:
            task = await TaskManager.get_root_task(session, queue_item.task)
            executor = get_executor_for_task(task)
            queue_item = await executor.sync_task_history(session, queue_item)
        queue_item.sync_in_progress_started_at = None
        return await TaskHistoryManager.save(session, queue_item)


def get_executor_for_task(task: Task) -> BaseExecutor:
    """Get the executor for a specific task.

    :param task: The task for which to get the executor.
    :type task: Task
    :return: The executor for the task.
    :rtype: BaseExecutor
    """
    try:
        return get_executor(task.backend)
    except ValueError:
        raise HTTPBadRequestException(
            f"Unsupported task backend: {task.backend}"
        ) from None
