import asyncio
from typing import Any
import logging
from app.tasks.utils import _process_queue_item
from asgiref.sync import async_to_sync

from celery import shared_task
logger = logging.getLogger(__name__)


async def execute_task(queue_id: int):
    await _process_queue_item(queue_id)
    
@shared_task(
    bind=True,autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    name='celery:trigger_task'
)
def trigger_task(self, queue_id: int = None):
    async_to_sync(execute_task)(queue_id)
    
    return {"status": "Task completed successfully", "queue_id": queue_id}