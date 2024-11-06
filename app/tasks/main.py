"""Define routes for the Tasks API."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from os import getenv

from celery.utils.log import get_task_logger
from fastapi import FastAPI

from app.core.config import create_app, default_lifespan, settings
from app.tasks.celery.celery_scheduler import setup_periodic_tasks
from app.tasks.config import tasks_settings
from app.tasks.db import init_tasks_db
from app.tasks.routes import schedules, tasks

logger = logging.getLogger(__name__)
celery_logger = get_task_logger(__name__)


DEFAULT_BACKEND_POLL_INTERVAL_SECONDS = 5
# TODO: Make all these getenv proper settings  # noqa: TD002, TD003
BACKEND_POLL_INTERVAL_SECONDS = getenv(
    "TASKS_BACKEND_POLL_INTERVAL_SECONDS",
    DEFAULT_BACKEND_POLL_INTERVAL_SECONDS,
)

AVAILABLE_OWNERS = {
    "*": "Any",
    "archiver": "Data Archiver",
    "alters": "Schema Change",
}


@asynccontextmanager
async def tasks_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage the Tasks API's lifespan.

    Initializes the Tasks database data and ensures that the CasdoorSDK, the
    NomadExecutor, and any extra client sessions are properly managed during the
    application's startup and shutdown phases.

    :param app: The FastAPI application instance.
    :type app: FastAPI
    :yield: None
    :rtype: AsyncGenerator[None, None]
    """
    await init_tasks_db()
    await setup_periodic_tasks()

    async with default_lifespan(app), tasks_settings.NOMAD:
        yield


lifespan = tasks_lifespan if __name__ == "__main__" else None
tasks_app = create_app(
    tasks.router,
    schedules.router,
    lifespan=lifespan, 
    add_cors_middleware=True
)


if __name__ == "__main__":
    # TODO: Rich formatting and custom logging handlers  # noqa: TD002, TD003
    logging.basicConfig(
        level=settings.LOGGING,
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> %(module)s.%(funcName)s - %(message)s",
    )
    for name, level in settings.LOGGING_EXTRA.items():
        logging.getLogger(name).setLevel(level)

    import uvicorn

    uvicorn.run(
        tasks_app,
        host=tasks_settings.UVICORN_HOST,
        port=tasks_settings.UVICORN_PORT,
        ssl_keyfile=tasks_settings.SSL_KEYFILE,
        ssl_certfile=tasks_settings.SSL_CERTFILE,
    )
