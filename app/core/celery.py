"""Configure and manage Celery application instances.

This module defines functions to create and configure a Celery app instance,
and retrieve task information by task ID.
"""

from celery import current_app as current_celery_app
from celery.local import Proxy
from celery.result import AsyncResult

from app.core.config import settings


def create_celery() -> Proxy:
    """Create and configure a Celery app instance.

    This function initializes the Celery app with settings from the configuration file.
    It sets various options such as task tracking, serialization, content types,
    result expiration, and worker-related configurations.

    :return: The configured Celery app instance.
    :rtype: Proxy
    """
    celery_app = current_celery_app
    celery_app.config_from_object(settings.CELERY, namespace="CELERY")
    return celery_app


def get_task_info(task_id: str) -> dict:
    """Return task info for the given task_id.

    :param task_id: The unique identifier of the Celery task.
    :type task_id: str
    :return: Task information with 'task_id' (str), 'task_status' (str),
        and 'task_result' (Any).
    :rtype: dict
    """
    task_result = AsyncResult(task_id)
    return {
        "task_id": task_id,
        "task_status": task_result.status,
        "task_result": task_result.result,
    }
