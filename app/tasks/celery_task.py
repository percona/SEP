"""Execute and Trigger Celery tasks.

This module defines functions for executing tasks asynchronously via Celery,
along with utility functions to process queue items.
"""

import logging
from typing import Any

from asgiref.sync import async_to_sync
from celery import shared_task, Task

from app.tasks.utils import process_queue_item

logger = logging.getLogger(__name__)


async def execute_task(queue_id: int) -> None:
    """Execute a task asynchronously by processing the given queue item.

    :param queue_id: The ID of the queue item to process.
    :type queue_id: int
    """
    await process_queue_item(queue_id)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    name="celery:trigger_task",
)
def trigger_task(self: Task, queue_id: int | None = None) -> dict[str, Any]:  # noqa: ARG001
    """Trigger a Celery task by executing a queue item.

    :param self: The Celery task instance.
    :type self: celery.Task
    :param queue_id: The ID of the queue item to trigger (optional).
    :type queue_id: int, optional
    :return: A dictionary containing the status and queue ID.
    :rtype: dict[str, Any]
    """
    logger.info("Executing task with queue_id: %s", queue_id)

    async_to_sync(execute_task)(queue_id)
    return {"status": "Task completed successfully", "queue_id": queue_id}
