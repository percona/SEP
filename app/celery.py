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

"""Define the shared Celery application for SEP."""

import asyncio
import logging.config
from typing import Any

from celery import Celery
from celery.signals import setup_logging, worker_process_init

from app.core.config import settings

logger = logging.getLogger(__name__)

celery = Celery("sep", **settings.CELERY.model_dump())

celery.loop = asyncio.new_event_loop()
asyncio.set_event_loop(celery.loop)


@setup_logging.connect
def setup_logging(**_kwargs: Any) -> None:
    """Define Celery signal to set up logging according to settings."""
    logging.config.dictConfig(settings.LOGGING_CONFIG)


@worker_process_init.connect
def init_child_event_loop(**kwargs: Any) -> None:
    """Initialize a new event loop for each worker process."""
    logger.debug("Initializing new event loop for worker process")
    celery.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(celery.loop)
