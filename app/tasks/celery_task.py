"""Module for executing and triggering Celery tasks.

This module defines functions for executing tasks asynchronously via Celery,
along with utility functions to process queue items.
"""

import logging

from asgiref.sync import async_to_sync
from celery import shared_task, Task

from app.tasks.utils import process_queue_item

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
def trigger_task(self: Task, queue_id: int | None = None) -> dict:
    """Trigger a Celery task by executing a queue item.

    :param self: The Celery task instance.
    :param queue_id: The ID of the queue item to trigger (optional).
    :return: A dictionary containing the status and queue ID.
    """
    self.logger.info("Executing task with queue_id: %s", queue_id)

    async_to_sync(execute_task)(queue_id)
    return {"status": "Task completed successfully", "queue_id": "queue_id"}
