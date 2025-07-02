# Copyright (C) 2025 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

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
