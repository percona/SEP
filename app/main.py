"""Define the main FastAPI app."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.inventory.main import inventory_app
from app.sep.config import sep_settings
from app.sep.main import sep_app
from app.tasks.main import tasks_app, tasks_lifespan


def create_app() -> FastAPI:
    """Create and configure the FastAPI app.

    :return: An instance of the FastAPI application with an attached Celery app.
    :rtype: FastAPI
    """
    current_app = FastAPI(lifespan=tasks_lifespan)

    if settings.BACKEND_CORS_ORIGINS:
        current_app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                str(origin).strip("/") for origin in settings.BACKEND_CORS_ORIGINS
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    current_app.include_router(api_router, prefix="/api")
    current_app.mount("/api/inventory", inventory_app)
    current_app.mount("/api/tasks", tasks_app)
    current_app.mount("/", sep_app)

    return current_app


app = create_app()

if __name__ == "__main__":
    # TODO: Rich formatting and custom logging handlers  # noqa: TD002, TD003
    logging.basicConfig(
        level=settings.LOGGING,
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> %(module)s.%(funcName)s - %(message)s",
    )
    logging.debug("CELERY_Config, %s", settings.CELERY)
    for name, level in settings.LOGGING_EXTRA.items():
        logging.getLogger(name).setLevel(level)

    import uvicorn

    uvicorn.run(
        app,
        host=sep_settings.UVICORN_HOST,
        port=sep_settings.UVICORN_PORT,
    )
