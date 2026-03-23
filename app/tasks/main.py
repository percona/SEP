# Copyright (C) 2026 Percona LLC
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

"""Define routes for the Tasks API."""

import json
import logging.config
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from celery.utils.log import get_task_logger
from fastapi import FastAPI, HTTPException, Request, status
from nomad.api.exceptions import BaseNomadException

from app.core.config import create_app, default_lifespan, settings
from app.tasks.config import tasks_settings
from app.tasks.db.seed import init_tasks_db
from app.tasks.execution.exceptions import TaskDataNotFoundInExecutorError
from app.tasks.periodic.routes import router as periodic_router
from app.tasks.routes import router as tasks_router

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
    tasks_router,
    periodic_router,
    lifespan=lifespan,
    backend_cors_origins=tasks_settings.BACKEND_CORS_ORIGINS,
    allowed_hosts=tasks_settings.ALLOWED_HOSTS,
    security_headers=tasks_settings.SECURITY_HEADERS,
)


@tasks_app.exception_handler(status.HTTP_500_INTERNAL_SERVER_ERROR)
async def internal_error_handler(
    _: Request,
    exc: BaseException,
) -> None:
    """Proper log unhandled exceptions."""
    logger.exception("Unhandled exception:", exc_info=exc)
    raise exc


def task_data_not_found_detail(exc: TaskDataNotFoundInExecutorError) -> dict[str, Any]:
    """Build structured detail for HTTP 410 from TaskDataNotFoundInExecutorError.

    :param exc: The exception indicating task data was not found in the executor.
    :type exc: TaskDataNotFoundInExecutorError
    :return: A dictionary with message and optional resource_type, resource_id,
        executor_name, job_id, evaluation_id, and detail keys for use in an HTTP 410
        response body.
    :rtype: dict[str, Any]
    """
    detail = {
        "message": "The requested task data is no longer available in the executor.",
    }
    if exc.resource_type is not None:
        detail["resource_type"] = exc.resource_type
    if exc.resource_id is not None:
        detail["resource_id"] = exc.resource_id
    if exc.executor_name is not None:
        detail["executor_name"] = exc.executor_name
    if exc.job_id is not None:
        detail["job_id"] = exc.job_id
    if exc.evaluation_id is not None:
        detail["evaluation_id"] = exc.evaluation_id
    if str(exc):
        detail["detail"] = str(exc)
    return detail


@tasks_app.exception_handler(TaskDataNotFoundInExecutorError)
async def task_data_not_found_handler(
    _: Request,
    exc: TaskDataNotFoundInExecutorError,
) -> None:
    """Handle exceptions raised when task data is not found in the executor."""
    payload = task_data_not_found_detail(exc)
    logger.debug(
        "Task data not found in executor; HTTP %s body: %s",
        status.HTTP_410_GONE,
        json.dumps(payload, default=str),
    )
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=payload)


@tasks_app.exception_handler(BaseNomadException)
async def nomad_exception_handler(_: Request, exc: BaseNomadException) -> None:
    """Handle exceptions raised by Nomad."""
    logger.exception("Error getting a response from Nomad", exc_info=exc)
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Failed to get a response from Nomad, make sure the agent is online.",
    )


if __name__ == "__main__":
    logging.config.dictConfig(settings.LOGGING_CONFIG)

    import uvicorn

    uvicorn.run(
        "app.tasks.main:tasks_app",
        host=tasks_settings.UVICORN_HOST,
        port=tasks_settings.UVICORN_PORT,
        ssl_keyfile=tasks_settings.SSL_KEYFILE,
        ssl_certfile=tasks_settings.SSL_CERTFILE,
        log_config=settings.LOGGING_CONFIG,
        reload=True,
        reload_dirs=[str(settings.BASE_DIR), str(settings.BASE_DIR / "app")],
        reload_includes=[f"{settings.BASE_DIR.name}/settings.yaml"],
        reload_excludes=[f"{settings.BASE_DIR.name}/*.py"],
    )
