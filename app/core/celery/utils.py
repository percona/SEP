# Copyright (C) 2025 Percona LLC
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

"""Configure Celery application.

Provides functions to initialize and set up a Celery app instance.
"""

from typing import Any, NamedTuple

from sqlalchemy_celery_beat import PeriodicTask

from app.core.celery.crud import BasePeriodicTaskManager, IntervalScheduleManager
from app.core.celery.db import get_async_session_maker
from app.core.celery.models import IntervalSchedule


class SystemPeriodicTaskData(NamedTuple):
    """Define structure to hold information about system periodic tasks.

    :param name: Name of the periodic task.
    :type name: str
    :param task_name: Name of the Celery task.
    :type task_name: str
    :param extra_kwargs: Optional keyword arguments for the periodic task.
    :type extra_kwargs: dict[str, Any] | None
    """

    name: str
    task_name: str
    extra_kwargs: dict[str, Any] | None = None


class SystemPeriodicTaskSchedule(NamedTuple):
    """Define structure for system periodic task schedules.

    This model is used to represent the schedule of system periodic tasks
    in the database.

    :param schedule: The interval schedule for the periodic task.
    :type schedule: IntervalSchedule
    :param tasks: List of system periodic tasks associated with the schedule.
    :type tasks: list[SystemPeriodicTaskData]
    """

    schedule: IntervalSchedule
    tasks: list[SystemPeriodicTaskData]


async def init_periodic_tasks_db(
    periodic_tasks: list[SystemPeriodicTaskSchedule], prefix_filter: str
) -> None:
    """Initialize the database with required periodic tasks.

    This function creates or updates periodic tasks in the Celery beat database
    based on the provided periodic tasks dictionary. It also removes any orphaned tasks
    that match the prefix filter.

    :param periodic_tasks: A dictionary where keys are `IntervalSchedule` instances
        and values are lists of tuples containing task details.
    :type periodic_tasks: dict[IntervalSchedule, list[tuple[str, str, dict[str, Any]]]]
    :param prefix_filter: Prefix to filter tasks for deletion.
    :type prefix_filter: str
    """
    celery_beat_async_session = get_async_session_maker()
    system_task_names = [
        "celery.backend_cleanup",
        "app.tasks.celery.execute_task_by_name",
    ]
    async with celery_beat_async_session() as celery_beat_session:
        for schedule, tasks in periodic_tasks:
            created_schedule, _ = await IntervalScheduleManager.get_or_create(
                celery_beat_session, schedule
            )
            for periodic_task_name, task_name, optional_extra_kwargs in tasks:
                extra_kwargs = optional_extra_kwargs or {}
                system_task_names.append(task_name)
                if (
                    periodic_task := (
                        await BasePeriodicTaskManager.first(
                            celery_beat_session, task=task_name
                        )
                    )
                ) is None:
                    periodic_task = PeriodicTask(
                        name=periodic_task_name,
                        task=task_name,
                        schedule_model=created_schedule,
                        **extra_kwargs,
                    )
                else:
                    periodic_task.schedule_model = created_schedule
                    periodic_task.name = periodic_task_name
                    for key, value in extra_kwargs.items():
                        setattr(periodic_task, key, value)
                celery_beat_session.add(periodic_task)
        await BasePeriodicTaskManager.delete_where(
            celery_beat_session,
            PeriodicTask.task.not_in(system_task_names),
            PeriodicTask.name.startswith(prefix_filter),
        )
        await celery_beat_session.commit()
