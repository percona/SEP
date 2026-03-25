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

"""Define the main FastAPI app."""

import logging.config
from argparse import ArgumentParser
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from multiprocessing import Process

from fastapi import FastAPI

from app.api.main import api_router
from app.celery import celery as celery_app
from app.core.config import create_app, settings
from app.core.utils import validate_importable_settings
from app.inventory.main import inventory_app
from app.sep.config import sep_settings
from app.sep.main import sep_app, sep_startup
from app.tasks.main import tasks_app, tasks_lifespan


@asynccontextmanager
async def main_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage the app's lifespan.

    Initializes the Tasks database data, the periodic tasks data, and ensures that the
    CasdoorSDK, the NomadExecutor, and any extra client sessions are properly managed
    during the application's startup and shutdown phases.

    :param app: The FastAPI application instance.
    :type app: FastAPI
    :yield: None
    :rtype: AsyncGenerator[None, None]
    """
    validate_importable_settings(
        settings.AUTH_USER_MODEL,
        *(s.syncer for s in sep_settings.SYNCERS),
    )
    await sep_startup()
    async with tasks_lifespan(app):
        yield


app = create_app(
    api_router,
    lifespan=main_lifespan,
    backend_cors_origins=sep_settings.BACKEND_CORS_ORIGINS,
    allowed_hosts=sep_settings.ALLOWED_HOSTS,
    security_headers=sep_settings.SECURITY_HEADERS,
)
app.mount("/api/inventory", inventory_app)
app.mount("/api/tasks", tasks_app)
app.mount("/", sep_app)


def start_celery_worker() -> None:
    """Start the Celery worker process."""
    worker = celery_app.Worker(
        include=["app.tasks.celery", "app.sep.celery"],
    )
    worker.start()


def start_celery_beat() -> None:
    """Start the Celery beat process."""
    beat = celery_app.Beat(
        scheduler="sqlalchemy",
        loglevel=settings.LOGGING_CONFIG["loggers"]["celery.beat"]["level"],
    )
    beat.run()


if __name__ == "__main__":
    import uvicorn

    parser = ArgumentParser()
    parser.add_argument(
        "--start-celery",
        action="store_true",
        default=False,
        help="Start the celery worker and beat processes",
    )
    args = parser.parse_args()

    if args.start_celery:
        logging.config.dictConfig(settings.LOGGING_CONFIG)

        celery_worker_process = Process(target=start_celery_worker)
        logging.info("Starting Celery worker...")
        celery_worker_process.start()

        celery_beat_process = Process(target=start_celery_beat)
        logging.info("Starting Celery beat for periodic tasks...")
        celery_beat_process.start()

        try:
            uvicorn.run(
                "app.main:app",
                host=sep_settings.UVICORN_HOST,
                port=sep_settings.UVICORN_PORT,
                log_config=settings.LOGGING_CONFIG,
                reload=sep_settings.UVICORN_RELOAD,
                reload_dirs=[str(settings.BASE_DIR), str(settings.BASE_DIR / "app")],
                reload_includes=[f"{settings.BASE_DIR.name}/settings.yaml"],
                reload_excludes=[f"{settings.BASE_DIR.name}/*.py"],
            )
        except KeyboardInterrupt:
            logging.info("Shutting down Celery worker...")
            logging.info("Shutting down Celery beat...")
        finally:
            celery_worker_process.terminate()
            celery_worker_process.join()
            celery_beat_process.terminate()
            celery_beat_process.join()

    else:
        logging.config.dictConfig(settings.LOGGING_CONFIG)
        uvicorn.run(
            "app.main:app",
            host=sep_settings.UVICORN_HOST,
            port=sep_settings.UVICORN_PORT,
            log_config=settings.LOGGING_CONFIG,
            reload=sep_settings.UVICORN_RELOAD,
            reload_dirs=[str(settings.BASE_DIR), str(settings.BASE_DIR / "app")],
            reload_includes=[f"{settings.BASE_DIR.name}/settings.yaml"],
            reload_excludes=[f"{settings.BASE_DIR.name}/*.py"],
        )
