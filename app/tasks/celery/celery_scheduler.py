"""Sets up periodic tasks in RedBeat for Celery.

using unique crontab periods from the database.
"""

from celery.schedules import crontab
from celery.utils.log import get_task_logger
from redbeat import RedBeatSchedulerEntry

from app.core.celery import create_celery
from app.tasks.crud import PeriodicTaskManager
from app.tasks.deps import SessionDep

celery_logger = get_task_logger(__name__)


async def setup_periodic_tasks(session: SessionDep) -> None:
    """Set up periodic tasks in RedBeat based on distinct crontab periods.

    :param session: Database session to use for querying crontab periods.
    :return: None
    """
    crontab_periods = await PeriodicTaskManager.list_distinct_crontab_periods(
        session=session
    )

    try:
        celery_logger.info("Setting up periodic tasks in RedBeat")

        for crontab_period in crontab_periods:
            schedule_name = f"task_{crontab_period.to_str()}"
            entry = RedBeatSchedulerEntry(
                schedule_name,
                "app.tasks.celery.celery_task.beat_task",
                crontab(minute=crontab_period.minute),
                args=[crontab_period.to_str(), schedule_name],
                app=create_celery(),
            )
            entry.save()

        celery_logger.info("Periodic tasks have been set up successfully.")

    except Exception:
        celery_logger.exception(
            "An exception occurred while setting up periodic tasks."
        )
