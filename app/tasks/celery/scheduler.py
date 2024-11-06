"""Sets up periodic tasks in RedBeat for Celery.

using unique crontab periods from the database.
"""

from celery.exceptions import NotRegistered
from celery.schedules import crontab
from celery.utils.log import get_task_logger
from redbeat import RedBeatSchedulerEntry

from app.tasks.celery.task import celery
from app.tasks.crud import PeriodicTaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import SessionDep
from app.tasks.models import CrontabPeriod, PeriodicTask

celery_logger = get_task_logger(__name__)


async def get_or_create_redbeat_entry(
    schedule_name: str, crontab_period: CrontabPeriod
) -> None:
    """Get an existing RedBeat entry or create a new one if it doesn't exist.

    :param schedule_name: The name of the RedBeat schedule entry.
    :type schedule_name: str
    :param crontab_period: The crontab period object defining the schedule.
    :type crontab_period: CrontabPeriod
    """
    try:
        existed_entry = RedBeatSchedulerEntry.from_key(
            "redbeat:" + schedule_name, app=celery
        )
    except KeyError:
        existed_entry = None

    if not existed_entry:
        entry = RedBeatSchedulerEntry(
            schedule_name,
            "app.tasks.celery.task.beat_task",
            crontab(minute=crontab_period.minute),
            args=[crontab_period.to_str(), schedule_name],
            app=celery,
        )
        entry.save()
        celery_logger.info(
            "Periodic task '%s' has been set up successfully.", schedule_name
        )
    return existed_entry


async def setup_periodic_tasks() -> None:
    """Set up periodic tasks in RedBeat based on distinct crontab periods."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        crontab_periods = await PeriodicTaskManager.list_distinct_crontab_periods(
            session=session
        )

        celery_logger.info("Setting up periodic tasks in RedBeat")
        for crontab_period in crontab_periods:
            schedule_name = f"task_{crontab_period.to_str()}"
            try:
                await get_or_create_redbeat_entry(schedule_name, crontab_period)
            except NotRegistered:
                celery_logger.exception(
                    "An exception occurred while setting up \
                    periodic task '%s'.",
                    schedule_name,
                )
            except Exception:
                celery_logger.exception(
                    "An unexpected error occurred while setting up \
                    periodic task '%s'.",
                    schedule_name,
                )

        celery_logger.info("Periodic tasks have been set up successfully.")


async def setup_periodic_task(periodic_task: PeriodicTask) -> None:
    """Set up a single periodic task in RedBeat.

    :param periodic_task: The periodic task to set up.
    :type periodic_task: PeriodicTask
    """
    crontab_period = CrontabPeriod.from_str(periodic_task.period)
    schedule_name = f"task_{crontab_period.to_str()}"
    try:
        await get_or_create_redbeat_entry(schedule_name, crontab_period)
    except NotRegistered:
        celery_logger.exception(
            "An exception occurred while setting up periodic task '%s'.",
            schedule_name,
        )
    except Exception:
        celery_logger.exception(
            "An unexpected error occurred while setting up periodic task '%s'.",
            schedule_name,
        )


async def remove_periodic_task(
    session: SessionDep, periodic_task: PeriodicTask
) -> None:
    """Remove a task from RedBeat if no related tasks are scheduled.

    :param session: The database session dependency.
    :type session: SessionDep
    :param periodic_task: The periodic task to remove.
    :type periodic_task: PeriodicTask
    """
    periodic_tasks = await PeriodicTaskManager.list_by_period(
        session=session,
        period=periodic_task.period,
        select_related_task=True,
    )

    if not periodic_tasks:
        schedule_name = f"task_{periodic_task.period}"
        try:
            entry = RedBeatSchedulerEntry.from_key(
                "redbeat:" + schedule_name, app=celery
            )
            if entry:
                entry.delete()
                celery_logger.info(
                    "Periodic task '%s' has been removed successfully.", schedule_name
                )
        except KeyError:
            celery_logger.warning(
                "Periodic task '%s' not found, nothing to remove.", schedule_name
            )
        except Exception:
            celery_logger.exception(
                "An unexpected error occurred while removing periodic task '%s'.",
                schedule_name,
            )
