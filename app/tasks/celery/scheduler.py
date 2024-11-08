"""Sets up periodic tasks in SQLAlchemy-Celery-Beat for Celery.

using unique crontab periods from the database.
"""

import json
from typing import Any

from celery.utils.log import get_task_logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy_celery_beat.models import (
    CrontabSchedule,
)
from sqlalchemy_celery_beat.models import (
    PeriodicTask as PeriodicTaskScheduler,
)
from sqlalchemy_celery_beat.session import SessionManager

from app.core.config import settings
from app.tasks.crud import PeriodicTaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import SessionDep
from app.tasks.models import CrontabPeriod, PeriodicTask

celery_logger = get_task_logger(__name__)


async def get_or_create_celery_beat_entry(
    schedule_name: str, crontab_period: CrontabPeriod, session: Any
) -> None:
    """Get an existing SQLAlchemy-Celery-Beat entry.

    OR create a new one if it doesn't exist.

    :param schedule_name: The name of the SQLAlchemy-Celery-Beat
        schedule entry.
    :type schedule_name: str
    :param crontab_period: The crontab period object defining the schedule.
    :type crontab_period: CrontabPeriod
    """
    try:
        schedule = (
            session.query(CrontabSchedule)
            .filter_by(
                minute=crontab_period.minute,
                hour=crontab_period.hour,
                day_of_week=crontab_period.day_of_week,
                day_of_month=crontab_period.day_of_month,
                month_of_year=crontab_period.month_of_year,
            )
            .first()
        )
        if not schedule:
            schedule = CrontabSchedule(
                minute=crontab_period.minute,
                hour=crontab_period.hour,
                day_of_week=crontab_period.day_of_week,
                day_of_month=crontab_period.day_of_month,
                month_of_year=crontab_period.month_of_year,
                timezone="UTC",
            )
            session.add(schedule)
            session.commit()

        periodic_task = (
            session.query(PeriodicTaskScheduler).filter_by(name=schedule_name).first()
        )
        if not periodic_task:
            periodic_task = PeriodicTaskScheduler(
                schedule_model=schedule,
                name=schedule_name,
                task="app.tasks.celery.task.beat_task",
                args=json.dumps([crontab_period.to_str(), schedule_name]),
            )
            session.add(periodic_task)
            session.commit()
    except SQLAlchemyError:
        celery_logger.exception(
            "Error setting up SQLAlchemy-Celery-Beat entry for %s", schedule_name
        )
        session.rollback()
        raise


async def setup_periodic_tasks() -> None:
    """Set up periodic tasks in SQLAlchemy-Celery-Beat.

    Based on distinct crontab periods.
    """
    session_manager = SessionManager()
    scheduler_session = session_manager.session_factory(settings.CELERY.BEAT_DBURI)
    async_session = get_async_session_maker()
    async with async_session() as session:
        crontab_periods = await PeriodicTaskManager.list_distinct_crontab_periods(
            session=session
        )

        celery_logger.info("Setting up periodic tasks in SQLAlchemy-Celery-Beat")
        for crontab_period in crontab_periods:
            schedule_name = f"task_{crontab_period.to_str()}"
            try:
                await get_or_create_celery_beat_entry(
                    schedule_name, crontab_period, scheduler_session
                )
            except SQLAlchemyError:
                celery_logger.exception(
                    "Failed to set up periodic task %s", schedule_name
                )
        celery_logger.info("Periodic tasks have been set up successfully.")


async def setup_periodic_task(periodic_task: PeriodicTask) -> None:
    """Set up a single periodic task in SQLAlchemy-Celery-Beat.

    :param periodic_task: The periodic task to set up.
    :type periodic_task: PeriodicTask
    """
    session_manager = SessionManager()
    scheduler_session = session_manager.session_factory(settings.CELERY.BEAT_DBURI)
    crontab_period = CrontabPeriod.from_str(periodic_task.period)
    schedule_name = f"task_{crontab_period.to_str()}"
    try:
        await get_or_create_celery_beat_entry(
            schedule_name, crontab_period, scheduler_session
        )
    except SQLAlchemyError:
        celery_logger.exception("Failed to set up periodic task %s", schedule_name)


async def remove_periodic_task(
    session: SessionDep, periodic_task: PeriodicTask
) -> None:
    """Remove a task from SQLAlchemy-Celery-Beat.

    If no related tasks are scheduled.

    :param session: The database session dependency.
    :type session: SessionDep
    :param periodic_task: The periodic task to remove.
    :type periodic_task: PeriodicTask
    """
    session_manager = SessionManager()
    scheduler_session = session_manager.session_factory(settings.CELERY.BEAT_DBURI)
    periodic_tasks = await PeriodicTaskManager.list_by_period(
        session=session,
        period=periodic_task.period,
        select_related_task=True,
    )

    if not periodic_tasks:
        schedule_name = f"task_{periodic_task.period}"

        try:
            # Find and delete the related periodic task scheduler entry
            periodic_task_entry = (
                scheduler_session.query(PeriodicTaskScheduler)
                .filter_by(name=schedule_name)
                .first()
            )
            if periodic_task_entry:
                scheduler_session.delete(periodic_task_entry)
                scheduler_session.commit()

            crontab_period = CrontabPeriod.from_str(periodic_task.period)
            # Find and delete the related crontab schedule entry
            crontab_schedule = (
                scheduler_session.query(CrontabSchedule)
                .filter_by(
                    minute=crontab_period.minute,
                    hour=crontab_period.hour,
                    day_of_week=crontab_period.day_of_week,
                    day_of_month=crontab_period.day_of_month,
                    month_of_year=crontab_period.month_of_year,
                )
                .first()
            )
            if crontab_schedule:
                scheduler_session.delete(crontab_schedule)
                scheduler_session.commit()

            celery_logger.info(
                "Removed periodic task %s and associated schedule.",
                schedule_name,
            )

        except SQLAlchemyError:
            celery_logger.exception("Failed to set up periodic task %s", schedule_name)
            session.rollback()  # Roll back in case of error
            raise
