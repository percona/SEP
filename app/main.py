"""Define the main FastAPI app."""

import logging.config
from argparse import ArgumentParser
from multiprocessing import Process

from app.api.main import api_router
from app.core.config import create_app, settings
from app.inventory.main import inventory_app
from app.sep.config import sep_settings
from app.sep.main import sep_app
from app.tasks.celery import celery as celery_app
from app.tasks.main import tasks_app, tasks_lifespan

app = create_app(
    api_router,
    lifespan=tasks_lifespan,
    add_cors_middleware=True,
    allowed_hosts=sep_settings.ALLOWED_HOSTS,
)
app.mount("/api/inventory", inventory_app)
app.mount("/api/tasks", tasks_app)
app.mount("/", sep_app)


def start_celery_worker() -> None:
    """Start the Celery worker process."""
    worker = celery_app.Worker(
        include=["app.tasks.celery"],
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

    else:
        logging.config.dictConfig(settings.LOGGING_CONFIG)
        uvicorn.run(
            app,
            host=sep_settings.UVICORN_HOST,
            port=sep_settings.UVICORN_PORT,
            log_config=settings.LOGGING_CONFIG,
        )
