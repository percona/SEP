"""Configure Celery and execute tasks for processing queue items."""

import logging
from typing import Any

from asgiref.sync import async_to_sync
from celery import Task

from app.core.celery import create_celery
from app.tasks.utils import process_queue_item

logger = logging.getLogger(__name__)

celery = create_celery("tasks")


async def execute_task(queue_id: int) -> None:
    """Execute a task asynchronously by processing the given queue item.

    :param queue_id: The ID of the queue item to process.
    :type queue_id: int
    """
    await process_queue_item(queue_id)


@celery.task(bind=True)
def trigger_task(self: Task, queue_id: int | None = None) -> dict[str, Any]:
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
