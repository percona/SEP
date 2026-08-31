# Copyright (C) 2026 Percona LLC
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

from app.core.celery.crud import (
    BasePeriodicTaskManager,
    CrontabScheduleManager,
    IntervalScheduleManager,
)
from app.core.celery.db import get_async_session_maker
from app.core.celery.models import CrontabSchedule, IntervalSchedule
from app.core.utils.date_time import utc_now


class SystemPeriodicTaskData(NamedTuple):
    """Define structure to hold information about system periodic tasks.

    :param name: Name of the periodic task.
    :param task_name: Name of the Celery task.
    :param extra_kwargs: Optional keyword arguments for the periodic task.
    :param owner_app_key: Key of the app that owns this schedule, or ``None`` for
        platform tasks not gated by app state.
    :param due_on_first_seed: Whether a newly created row is marked due
        immediately, so beat dispatches it on the first load rather than one
        interval later. Applied on creation only, so an operator who clears the
        marker is not overridden on the next boot.
    """

    name: str
    task_name: str
    extra_kwargs: dict[str, Any] | None = None
    owner_app_key: str | None = None
    due_on_first_seed: bool = False


class SystemPeriodicTaskSchedule(NamedTuple):
    """Define structure for system periodic task schedules.

    This model is used to represent the schedule of system periodic tasks
    in the database.

    :param schedule: The schedule for the periodic task (interval or crontab).
    :type schedule: IntervalSchedule | CrontabSchedule
    :param tasks: List of system periodic tasks associated with the schedule.
    :type tasks: list[SystemPeriodicTaskData]
    """

    schedule: IntervalSchedule | CrontabSchedule
    tasks: list[SystemPeriodicTaskData]


async def init_periodic_tasks_db(
    periodic_tasks: list[SystemPeriodicTaskSchedule], prefix_filter: str
) -> None:
    """Initialize the database with required periodic tasks.

    This function creates or updates periodic tasks in the Celery beat database
    based on the provided periodic tasks dictionary. It also removes any orphaned tasks
    that match the prefix filter.

    An entry's ``due_on_first_seed`` marker is honoured only where the row is
    created, so an upgrade writes nothing to a schedule that already exists and
    an operator who cleared the marker is not overridden on the next boot.

    :param periodic_tasks: A list of schedule/task pairs to seed.
    :param prefix_filter: Prefix to filter tasks for deletion.
    """
    celery_beat_async_session = get_async_session_maker()
    system_task_names: list[str] = [
        "celery.backend_cleanup",
        "app.tasks.celery.execute_task_by_name",
    ]
    seeded_names: list[str] = []
    async with celery_beat_async_session() as celery_beat_session:
        for schedule, tasks in periodic_tasks:
            if isinstance(schedule, CrontabSchedule):
                created_schedule, _ = await CrontabScheduleManager.get_or_create(
                    celery_beat_session, schedule
                )
            else:
                created_schedule, _ = await IntervalScheduleManager.get_or_create(
                    celery_beat_session, schedule
                )
            for task in tasks:
                extra_kwargs = task.extra_kwargs or {}
                system_task_names.append(task.task_name)
                seeded_names.append(task.name)
                if (
                    periodic_task := (
                        await BasePeriodicTaskManager.first(
                            celery_beat_session, name=task.name
                        )
                    )
                ) is None:
                    periodic_task = PeriodicTask(
                        name=task.name,
                        task=task.task_name,
                        schedule_model=created_schedule,
                        **extra_kwargs,
                    )
                    if task.due_on_first_seed:
                        periodic_task.start_time = utc_now()
                else:
                    periodic_task.task = task.task_name
                    periodic_task.schedule_model = created_schedule
                    for key, value in extra_kwargs.items():
                        setattr(periodic_task, key, value)
                celery_beat_session.add(periodic_task)
        await BasePeriodicTaskManager.delete_where(
            celery_beat_session,
            PeriodicTask.name.not_in(seeded_names),
            PeriodicTask.name.startswith(prefix_filter),
        )
        await celery_beat_session.commit()
