"""Celery configuration module.

This module defines functions to create and configure a Celery app instance,
and retrieve task information by task ID.
"""

from celery import current_app as current_celery_app
from celery.result import AsyncResult
from httpx import Proxy

from app.core.config import settings


def create_celery() -> Proxy:
    """Create and configure a Celery app instance.

    This function initializes the Celery app with settings from the configuration file.
    It sets various options such as task tracking, serialization, content types,
    result expiration, and worker-related configurations.

    :return: The configured Celery app instance.
    """
    celery_app = current_celery_app
    celery_app.config_from_object(settings.CELERY, namespace="CELERY")
    celery_app.conf.update(task_track_started=True)
    celery_app.conf.update(task_serializer="pickle")
    celery_app.conf.update(result_serializer="pickle")
    celery_app.conf.update(accept_content=["pickle", "json"])
    celery_app.conf.update(result_expires=200)
    celery_app.conf.update(result_persistent=True)
    celery_app.conf.update(worker_send_task_events=False)
    celery_app.conf.update(worker_prefetch_multiplier=1)
    celery_app.conf.update(redbeat_lock_timeout=300)

    return celery_app


def get_task_info(task_id: str) -> dict:
    """Return task info for the given task_id."""
    task_result = AsyncResult(task_id)
    return {
        "task_id": task_id,
        "task_status": task_result.status,
        "task_result": task_result.result,
    }
