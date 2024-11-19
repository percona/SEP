"""Define the main FastAPI app."""

import logging.config
from multiprocessing import Process

from app.api.main import api_router
from app.core.config import create_app, settings
from app.inventory.main import inventory_app
from app.sep.config import sep_settings
from app.sep.main import sep_app
from app.tasks.celery import celery as celery_app
from app.tasks.main import tasks_app, tasks_lifespan

app = create_app(api_router, lifespan=tasks_lifespan, add_cors_middleware=True)
app.mount("/api/inventory", inventory_app)
app.mount("/api/tasks", tasks_app)
app.mount("/", sep_app)

if __name__ == "__main__":
    worker = celery_app.Worker(
        include=["app.tasks.celery"],
    )
    beat = celery_app.Beat(
        scheduler="sqlalchemy",
        loglevel=settings.LOGGING_CONFIG["loggers"]["celery.beat"]["level"],
    )
    logging.config.dictConfig(settings.LOGGING_CONFIG)
    celery_worker_process = Process(target=worker.start)
    logging.info("Starting Celery worker...")
    celery_worker_process.start()

    celery_beat_process = Process(target=beat.run)
    logging.info("Starting Celery beat for periodic tasks...")
    celery_beat_process.start()

    import uvicorn

    try:
        uvicorn.run(
            app,
            host=sep_settings.UVICORN_HOST,
            port=sep_settings.UVICORN_PORT,
            log_config=settings.LOGGING_CONFIG,
        )
    except KeyboardInterrupt:
        logging.info("Shutting down Celery worker...")
        logging.info("Shutting down Celery beat...")
    finally:
        celery_worker_process.terminate()
        celery_worker_process.join()
        celery_beat_process.terminate()
        celery_beat_process.join()
