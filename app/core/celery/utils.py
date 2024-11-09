"""Configure Celery application.

Provides functions to initialize and set up a Celery app instance.
"""

from celery import Celery

from app.core.config import settings


def create_celery(name: str) -> Celery:
    """Initialize a Celery app instance with configuration settings.

    :param name: Name for the Celery app instance.
    :type name: str
    :return: Configured Celery app instance.
    :rtype: Celery
    """
    return Celery(name, **settings.CELERY.model_dump())
