"""Define routes for the Tasks API."""

import logging.config
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from celery.utils.log import get_task_logger
from fastapi import FastAPI

from app.core.config import create_app, default_lifespan, settings
from app.tasks.config import tasks_settings
from app.tasks.db import init_tasks_db
from app.tasks.routes import periodic, tasks

logger = logging.getLogger(__name__)
celery_logger = get_task_logger(__name__)


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
    async with default_lifespan(app), tasks_settings.NOMAD:
        yield


lifespan = tasks_lifespan if __name__ == "__main__" else None
tasks_app = create_app(
    tasks.router, periodic.router, lifespan=lifespan, add_cors_middleware=True
)


if __name__ == "__main__":
    logging.config.dictConfig(settings.LOGGING_CONFIG)

    import uvicorn

    uvicorn.run(
        tasks_app,
        host=tasks_settings.UVICORN_HOST,
        port=tasks_settings.UVICORN_PORT,
        ssl_keyfile=tasks_settings.SSL_KEYFILE,
        ssl_certfile=tasks_settings.SSL_CERTFILE,
        log_config=settings.LOGGING_CONFIG,
    )
