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

"""Define models for periodic tasks in the Tasks app."""

import json
from datetime import datetime, timedelta, UTC
from typing import Any, Self
from zoneinfo import ZoneInfo

from croniter import croniter
from pydantic import (
    BaseModel,
    computed_field,
    Field,
    field_validator,
    model_validator,
)
from sqlalchemy_celery_beat.models import Period, PeriodicTask

from app.core.celery.models import CrontabSchedule, IntervalSchedule
from app.core.utils.fields import EmptyStrToNone, UTCDatetime
from app.tasks.models import TaskExecuteRequest, TaskHistoryStatusEnum


class PeriodicTaskExecuteRequest(TaskExecuteRequest):
    """Represent the execute request the periodic task will use for executions.

    :param meta: A dictionary of meta variables for the task execution.
        Defaults to an empty dictionary.
    :type meta: dict[str, Any]
    :param payload: Optional payload data or file path for the task execution.
        Defaults to None.
    :type payload: str | None
    :param eta: The earliest time the task can be executed. Forced to None, as periodic
        tasks are always executed on the defined schedule.
    :type eta: datetime | None
    """

    @field_validator("eta")
    @classmethod
    def _force_eta_to_none(cls, _: datetime | EmptyStrToNone) -> None:
        """Force field eta to None."""
        return


class BasePeriodicTask(BaseModel):
    """Define the base model for periodic tasks.

    :param name: The name of the periodic task.
    :type name: str
    :param task: The task identifier.
    :type task: str
    :param start_time: The start time for the task execution.
    :type start_time: UTCDatetime | None
    :param enabled: Whether the task is enabled.
    :type enabled: bool
    :param description: A description of the task.
    :type description: str
    :param execute_request: The execution request details for the task.
    :type execute_request: PeriodicTaskExecuteRequest | None
    :param interval: The interval schedule for the task. Defaults to None.
    :type interval: IntervalSchedule | None
    :param crontab: The crontab schedule for the task. Defaults to None.
    :type crontab: CrontabSchedule | None
    """

    name: str
    task: str
    start_time: UTCDatetime | None
    enabled: bool
    description: str
    execute_request: PeriodicTaskExecuteRequest | None = None
    interval: IntervalSchedule | None = None
    crontab: CrontabSchedule | None = None

    @computed_field
    @property
    def period(self) -> str:
        """Get the period string for the periodic task.

        Returns a string representation of the task's schedule based on whether it uses
        an interval or crontab schedule.

        :return: A string representing the task's period.
        :rtype: str
        """
        if self.interval is not None:
            return str(self.interval)
        return str(self.crontab)

    @model_validator(mode="after")
    def validate_one_schedule_is_set(self) -> Self:
        """Ensure that exactly one scheduling method is set.

        Validates that either `interval` or `crontab` is set, but not both.

        :return: The validated BasePeriodicTask instance.
        :rtype: Self
        :raises ValueError: If both or neither scheduling methods are set.
        """
        if self.interval is None and self.crontab is None:
            raise ValueError("Either `interval` or `crontab` must be set.")
        if self.interval is not None and self.crontab is not None:
            raise ValueError("Only one of `interval` or `crontab` can be set.")
        return self


class PeriodicTaskResponse(BasePeriodicTask):
    """Representing a response for a periodic task API call.

    This model extends `BasePeriodicTask` and includes additional fields such as ID,
    last run time, total run count, and date changed.

    :param name: The name of the periodic task.
    :type name: str
    :param task: The SEP task name.
    :type task: str
    :param start_time: The start time for the task execution.
    :type start_time: UTCDatetime | None
    :param enabled: Whether the task is enabled.
    :type enabled: bool
    :param description: A description of the task.
    :type description: str
    :param execute_request: The execution request details for the task.
    :type execute_request: PeriodicTaskExecuteRequest | None
    :param id: The unique identifier of the periodic task.
    :type id: int
    :param last_run_at: The datetime of the last run.
    :type last_run_at: UTCDatetime | None
    :param total_run_count: The total number of times the task has run.
    :type total_run_count: int
    :param date_changed: The datetime when the task was last changed.
    :type date_changed: UTCDatetime | None
    :param last_run_status: The result of this schedule's own most recent
        run, or ``None`` when the schedule has never run. Resolved as the
        earliest system-triggered history for this task name at or after the
        schedule's ``last_run_at``, so a later unrelated system run of the same
        task name is not misattributed.
    :type last_run_status: TaskHistoryStatusEnum | None
    :param interval: The interval schedule for the task. Defaults to None. This field
        is populated with the alias "model_intervalschedule".
    :type interval: IntervalSchedule | None
    :param crontab: The crontab schedule for the task. Defaults to None. This field
        is populated with the alias "model_crontabschedule".
    :type crontab: CrontabSchedule | None
    """

    id: int
    last_run_at: UTCDatetime | None
    last_run_status: TaskHistoryStatusEnum | None = None
    total_run_count: int = 0
    date_changed: UTCDatetime | None
    interval: IntervalSchedule | None = Field(
        None, validation_alias="model_intervalschedule"
    )
    crontab: CrontabSchedule | None = Field(
        None, validation_alias="model_crontabschedule"
    )

    @computed_field
    @property
    def next_run_at(self) -> UTCDatetime | None:
        """Compute the next scheduled execution time.

        Return the next execution time based on the task's schedule. For crontab
        schedules, use `croniter` to compute the next fire time from the cron
        expression in the schedule's timezone, converted to UTC. For interval
        schedules, add the interval duration to `last_run_at`, falling back to
        `start_time`, then the current time.

        :return: The next scheduled execution time in UTC, or `None` if the task
            is disabled.
        :rtype: UTCDatetime | None
        """
        if not self.enabled:
            return None
        if self.crontab is not None:
            tz = ZoneInfo(self.crontab.timezone)
            now = datetime.now(tz)
            cron_expr = (
                f"{self.crontab.minute} {self.crontab.hour} "
                f"{self.crontab.day_of_month} {self.crontab.month_of_year} "
                f"{self.crontab.day_of_week}"
            )
            return croniter(cron_expr, now).get_next(datetime).astimezone(UTC)
        if self.interval is not None:
            delta = timedelta(**{self.interval.period.value: self.interval.every})
            base = self.last_run_at or self.start_time or datetime.now(UTC)
            return base + delta
        return None

    @model_validator(mode="before")
    @classmethod
    def populate_task_data(cls, data: Any) -> Any:
        """Populate task data from a PeriodicTask instance or dictionary.

        Extracts task execution details from the provided data, which can be a
        `PeriodicTask` instance or a dictionary, and sets the `task` and
        `execute_request` fields.

        :param data: The input data containing task execution details.
        :type data: Any
        :return: The modified data with populated task fields.
        :rtype: Any
        """
        if isinstance(data, PeriodicTask):
            data = data.__dict__
        if isinstance(data, dict):
            extra_kwargs = {
                "task": None,
                "execute_request": None,
            }
            if (raw_args := data.get("args")) and (args := json.loads(raw_args)):
                extra_kwargs["task"] = args[0]
                if len(args) > 1:
                    extra_kwargs["execute_request"] = args[1]
            if (raw_kwargs := data.get("kwargs")) and (
                kwargs := json.loads(raw_kwargs)
            ):
                extra_kwargs["task"] = kwargs.get("task_name", extra_kwargs["task"])
                extra_kwargs["execute_request"] = kwargs.get(
                    "execution_data", extra_kwargs["execute_request"]
                )
            return data | extra_kwargs
        return data


class PeriodicTaskWrite(BasePeriodicTask):
    """Define the model for writing periodic tasks.

    This model extends `BasePeriodicTask` and includes additional fields required for
    creating or updating periodic tasks in the database.

    :param name: The name of the periodic task.
    :type name: str
    :param task: The Celery task name.
    :type task: str
    :param start_time: The start time for the task execution.
    :type start_time: UTCDatetime
    :param enabled: Whether the task is enabled.
    :type enabled: bool
    :param description: A description of the task.
    :type description: str
    :param execute_request: The execution request details for the task.
    :type execute_request: PeriodicTaskExecuteRequest | None
    :param interval: The interval schedule for the task. Defaults to None.
    :type interval: IntervalSchedule | None
    :param crontab: The crontab schedule for the task. Defaults to None.
    :type crontab: CrontabSchedule | None
    :param kwargs: A JSON string representing additional keyword arguments for the task.
    :type kwargs: str
    """

    kwargs: str

    @model_validator(mode="before")
    @classmethod
    def populate_celery_task_data(cls, data: Any) -> Any:
        """Populate Celery task data before validation.

        Transforms the input data to include the Celery task name and execution data.
        For updates, only includes execute_request if it was explicitly set.

        :param data: The input data containing task details.
        :type data: Any
        :return: The modified data with Celery task information.
        :rtype: Any
        """
        if isinstance(data, dict):
            extra_data = {
                "task": "app.tasks.celery.execute_task_by_name",
                "kwargs": {
                    "task_name": data.get("task"),
                },
            }
            if "execute_request" in data:
                extra_data["kwargs"]["execution_data"] = data.get("execute_request")
            return data | extra_data
        return data

    @field_validator("kwargs", mode="before")
    @classmethod
    def encode_kwargs(cls, v: Any) -> Any:
        """Encode the kwargs field to a JSON string.

        Converts the `kwargs` dictionary to a JSON string if it is a dictionary.

        :param v: The kwargs value to encode.
        :type v: Any
        :return: The encoded kwargs as a JSON string.
        :rtype: Any
        """
        if isinstance(v, dict):
            return json.dumps(v)
        return v

    @field_validator("interval")
    @classmethod
    def validate_min_interval(
        cls, v: IntervalSchedule | None
    ) -> IntervalSchedule | None:
        """Ensure the interval is not lower than 1 minute.

        :param v: The interval schedule to validate.
        :type v: IntervalSchedule | None
        :return: The validated interval schedule.
        :rtype: IntervalSchedule | None
        """
        if v is not None and v.period not in {
            Period.DAYS,
            Period.HOURS,
            Period.MINUTES,
        }:
            raise ValueError(
                f"Invalid period '{v.period}' for IntervalSchedule. Valid periods are: "
                f"'days', 'hours', 'minutes'."
            )
        return v


class PeriodicTaskUpdate(PeriodicTaskWrite):
    """Define the model for updating periodic tasks.

    Extends `PeriodicTaskWrite` and adds validations specific to updating tasks.

    :param name: The name of the periodic task.
    :type name: str
    :param task: The Celery task name.
    :type task: str
    :param start_time: The start time for the task execution.
    :type start_time: UTCDatetime | None
    :param enabled: Whether the task is enabled.
    :type enabled: bool
    :param description: A description of the task.
    :type description: str
    :param execute_request: The execution request details for the task.
    :type execute_request: PeriodicTaskExecuteRequest | None
    :param interval: The interval schedule for the task. Defaults to None.
    :type interval: IntervalSchedule | None
    :param crontab: The crontab schedule for the task. Defaults to None.
    :type crontab: CrontabSchedule | None
    :param kwargs: A JSON string representing additional keyword arguments for the task.
    :type kwargs: str
    """

    @field_validator("kwargs", mode="before")
    @classmethod
    def encode_kwargs(cls, v: Any) -> Any:
        """Encode the kwargs field and ensure required fields are present.

        Converts the `kwargs` dictionary to a JSON string and validates the presence
        of the 'task_name' field.

        :param v: The kwargs value to encode.
        :type v: Any
        :return: The encoded kwargs as a JSON string.
        :rtype: Any
        :raises ValueError: If 'task_name' is missing in kwargs.
        """
        if isinstance(v, dict):
            if v.get("task_name") is None:
                raise ValueError("Missing required field 'task_name'")
            return json.dumps(v)
        return v


class PeriodicTaskCreate(PeriodicTaskWrite):
    """Define the model for creating periodic tasks.

    Extends `PeriodicTaskWrite` and includes additional fields required for creating
    new periodic tasks.

    :param task: The Celery task name.
    :type task: str
    :param execute_request: The execution request details for the task.
    :type execute_request: PeriodicTaskExecuteRequest | None
    :param interval: The interval schedule for the task. Defaults to None.
    :type interval: IntervalSchedule | None
    :param crontab: The crontab schedule for the task. Defaults to None.
    :type crontab: CrontabSchedule | None
    :param kwargs: A JSON string representing additional keyword arguments for the task.
    :type kwargs: str
    :param name: The name of the periodic task. Defaults to an empty string, meaning
        the value will be automatically generated on create.
    :type name: str
    :param start_time: The start time for the task execution. Defaults to None.
    :type start_time:  UTCDatetime | None
    :param enabled: Whether the task is enabled. Defaults to True.
    :type enabled: bool
    :param description: A description of the task. Defaults to an empty string.
    :type description: str
    """

    name: str = ""
    start_time: UTCDatetime | None = None
    enabled: bool = True
    description: str = ""
