"""Configure Celery application.

Provides functions to initialize and set up a Celery app instance.
"""

import logging.config
from typing import Any

from celery import Celery
from celery.signals import setup_logging

from app.core.config import settings


def create_celery(name: str) -> Celery:
    """Initialize a Celery app instance with configuration settings.

    :param name: Name for the Celery app instance.
    :type name: str
    :return: Configured Celery app instance.
    :rtype: Celery
    """
    return Celery(name, **settings.CELERY.model_dump())


@setup_logging.connect
def setup_logging(**_kwargs: Any) -> None:
    """Define Celery signal to set up logging according to settings."""
    logging.config.dictConfig(settings.LOGGING_CONFIG)
