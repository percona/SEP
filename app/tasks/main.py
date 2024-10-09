"""Define routes for the Tasks API."""

import logging
from collections import namedtuple
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from os import getenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.tasks.config import tasks_settings
from app.tasks.db import get_async_session_maker
from app.tasks.db import init_db
from app.tasks.routes import router

logger = logging.getLogger(__name__)


DEFAULT_BACKEND_POLL_INTERVAL_SECONDS = 5
# TODO: Make all these getenv proper settings
BACKEND_POLL_INTERVAL_SECONDS = getenv(
    "TASKS_BACKEND_POLL_INTERVAL_SECONDS",
    DEFAULT_BACKEND_POLL_INTERVAL_SECONDS,
)

TaskOwner = namedtuple("TaskOwner", ["value", "label"])
TranslateConfig = namedtuple("TranslateConfig", ["old", "new", "action"])

TRANSLATION_MAPPING = {
    "create": (
        TranslateConfig("owners", "meta", "update"),
        TranslateConfig("taskalias", "name", "flatten"),
        TranslateConfig("taskdef", "data", "backend"),
        TranslateConfig("taskeng", "engine", "flatten"),
    ),
    "owners": (
        TaskOwner(None, "Any"),
        TaskOwner("archiver", "Data Archiver"),
        TaskOwner("alters", "Schema Change"),
    ),
}


@asynccontextmanager
async def initial_tasks_setup(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """Initialize Tasks database data."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        await init_db(session)
    yield


tasks_app = (
    FastAPI(lifespan=initial_tasks_setup) if __name__ == "__main__" else FastAPI()
)
tasks_app.include_router(router)
tasks_app.log = logger

if settings.BACKEND_CORS_ORIGINS:
    tasks_app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            str(origin).strip("/") for origin in settings.BACKEND_CORS_ORIGINS
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


if __name__ == "__main__":
    # TODO: Rich formatting and custom logging handlers
    logging.basicConfig(
        level=settings.LOGGING,
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> "
        "%(module)s.%(funcName)s - %(message)s",
    )
    logging.getLogger("sqlalchemy.engine").setLevel(settings.SQLALCHEMY_LOGGING)

    import uvicorn

    uvicorn.run(
        tasks_app,
        host=tasks_settings.UVICORN_HOST,
        port=tasks_settings.UVICORN_PORT,
        ssl_keyfile=tasks_settings.SSL_KEYFILE,
        ssl_certfile=tasks_settings.SSL_CERTFILE,
    )
