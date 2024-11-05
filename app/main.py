"""Define the main FastAPI app."""

import logging

from app.api.main import api_router
from app.core.config import create_app, settings
from app.inventory.main import inventory_app
from app.sep.config import sep_settings
from app.sep.main import sep_app
from app.tasks.main import tasks_app, tasks_lifespan

app = create_app(api_router, lifespan=tasks_lifespan, add_cors_middleware=True)
app.mount("/api/inventory", inventory_app)
app.mount("/api/tasks", tasks_app)
app.mount("/", sep_app)

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
