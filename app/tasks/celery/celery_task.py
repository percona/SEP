"""Module for executing and triggering Celery tasks.

This module defines functions for executing tasks asynchronously via Celery,
along with utility functions to process queue items.
"""

import logging

from asgiref.sync import async_to_sync
from celery import shared_task, Task
from redbeat import RedBeatSchedulerEntry

from app.core.celery import create_celery
from app.tasks.crud import PeriodicTaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.utils import prepare_task_history, process_queue_item

logger = logging.getLogger(__name__)


async def execute_task(queue_id: int) -> None:
    """Execute a task asynchronously by processing the given queue item.

    :param queue_id: The ID of the queue item to process.
    :return: None
    """
    await process_queue_item(queue_id)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    name="celery:trigger_task",
)
def trigger_task(self: Task, queue_id: int | None = None) -> dict:  # noqa: ARG001
    """Trigger a Celery task by executing a queue item.

    :param self: The Celery task instance.
    :param queue_id: The ID of the queue item to trigger (optional).
    :return: A dictionary containing the status and queue ID.
    """
    logger.info("Executing task with queue_id: %s", queue_id)

    async_to_sync(execute_task)(queue_id)
    return {"status": "Task completed successfully", "queue_id": queue_id}


@shared_task()
def beat_task(period: str, schedule_name: str) -> str:
    """Trigger a periodic task execution based on the specified time period."""
    logger.debug("Period: %s", period)

    async_to_sync(process_tasks_with_period)(period, schedule_name)
    return {"status": "Task completed successfully", "period": period}


async def process_tasks_with_period(period: str, schedule_name: str) -> None:
    """Asynchronously process tasks associated with a given period.

    Retrieve tasks, record their execution history, and trigger each
        for asynchronous execution.

    :param period: The time period for which to retrieve and process tasks.
    :return: None
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        periodic_tasks = await PeriodicTaskManager.list_by_period(
            session=session,
            period=period,
            select_related_task=True,
        )

        if not periodic_tasks:
            try:
                entry = RedBeatSchedulerEntry.from_key(
                    "redbeat:" + schedule_name, app=create_celery()
                )
            except KeyError:
                entry = None

            logger.debug("Remove entry, %s", entry)
            if entry:
                entry.delete()

        for periodic_task in periodic_tasks:
            history_recorded = await prepare_task_history(
                task_name=periodic_task.task.name,
                execution_data=periodic_task.execute_request,
            )
            if not history_recorded:
                logger.error("Failed to record task history.")

            trigger_task.apply_async(kwargs={"queue_id": history_recorded.id})
