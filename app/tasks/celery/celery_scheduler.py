"""Sets up periodic tasks in RedBeat for Celery.

using unique crontab periods from the database.
"""

from celery.schedules import crontab
from celery.utils.log import get_task_logger
from redbeat import RedBeatSchedulerEntry

from app.tasks.celery.celery_task import celery
from app.tasks.crud import PeriodicTaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import SessionDep
from app.tasks.models import CrontabPeriod, PeriodicTask

celery_logger = get_task_logger(__name__)


async def setup_periodic_tasks() -> None:
    """Set up periodic tasks in RedBeat based on distinct crontab periods."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        crontab_periods = await PeriodicTaskManager.list_distinct_crontab_periods(
            session=session
        )

        try:
            celery_logger.info("Setting up periodic tasks in RedBeat")
            for crontab_period in crontab_periods:
                schedule_name = f"task_{crontab_period.to_str()}"

                try:
                    existed_entry = RedBeatSchedulerEntry.from_key(
                        "redbeat:" + schedule_name, app=celery
                    )
                except KeyError:
                    existed_entry = None

                if not existed_entry:
                    entry = RedBeatSchedulerEntry(
                        schedule_name,
                        "app.tasks.celery.celery_task.beat_task",
                        crontab(minute=crontab_period.minute),
                        args=[crontab_period.to_str(), schedule_name],
                        app=celery,
                    )
                    entry.save()

            celery_logger.info("Periodic tasks have been set up successfully.")

        except Exception:
            celery_logger.exception(
                "An exception occurred while setting up periodic tasks."
            )


async def setup_periodic_task(periodic_task: PeriodicTask) -> None:
    """Set up a single periodic task in RedBeat."""
    crontab_period = CrontabPeriod.from_str(periodic_task.period)
    try:
        schedule_name = f"task_{crontab_period.to_str()}"

        try:
            existed_entry = RedBeatSchedulerEntry.from_key(
                "redbeat:" + schedule_name, app=celery
            )
        except KeyError:
            existed_entry = None

        if not existed_entry:
            entry = RedBeatSchedulerEntry(
                schedule_name,
                "app.tasks.celery.celery_task.beat_task",
                crontab(minute=crontab_period.minute),
                args=[crontab_period.to_str(), schedule_name],
                app=celery,
            )
            entry.save()
            celery_logger.info("Periodic task have been set up successfully.")

    except Exception:
        celery_logger.exception(
            "An exception occurred while setting up periodic tasks."
        )


async def remove_periodic_task(
    session: SessionDep, periodic_task: PeriodicTask
) -> None:
    """Remove a task from RedBeat if no related tasks are scheduled."""
    periodic_tasks = await PeriodicTaskManager.list_by_period(
        session=session,
        period=periodic_task.period,
        select_related_task=True,
    )

    if not periodic_tasks:
        try:
            entry = RedBeatSchedulerEntry.from_key(
                "redbeat:task_" + periodic_task.period, app=celery
            )
        except KeyError:
            entry = None

        if entry:
            entry.delete()
        celery_logger.info("Periodic task have been removed successfully.")
