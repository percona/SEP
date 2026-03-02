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

"""Define models for interacting with the Tasks API."""

from typing import Any

from pydantic import BaseModel, model_validator

from app.core.celery.models import CrontabSchedule, IntervalSchedule
from app.core.utils.fields import EmptyStrToNone, UTCDatetime
from app.tasks.periodic.models import (
    PeriodicTaskExecuteRequest,
)


class PeriodicTaskRequest(BaseModel):
    """Define the base model for writing periodic tasks from the SEP app.

    Every field defaults to None and only fields that were set are sent to the Tasks
    API.

    :param start_time: The start time for the task execution.
    :type start_time: UTCDatetime | EmptyStrToNone
    :param enabled: Whether the task is enabled.
    :type enabled: bool | EmptyStrToNone
    :param execute_request: The execution request details for the task.
    :type execute_request: PeriodicTaskExecuteRequest | EmptyStrToNone
    :param interval: The interval schedule for the task.
    :type interval: IntervalSchedule | EmptyStrToNone
    :param crontab: The crontab schedule for the task.
    :type crontab: CrontabSchedule | EmptyStrToNone
    """

    start_time: UTCDatetime | EmptyStrToNone = None
    enabled: bool | EmptyStrToNone = None
    execute_request: PeriodicTaskExecuteRequest | EmptyStrToNone = None
    interval: IntervalSchedule | EmptyStrToNone = None
    crontab: CrontabSchedule | EmptyStrToNone = None

    @model_validator(mode="before")
    @classmethod
    def set_period(cls, data: Any) -> Any:
        """Populate period (interval or crontab) data and execute_request fields.

        Transforms the input form data into the interval/crontab format.
        When setting one schedule type, clears the other to avoid conflicts.
        Also extracts keys prefixed with 'execute_request_' into execute_request.

        :param data: The form input.
        :type data: Any
        :return: The modified data with appropriate interval/crontab and execute_request
            fields.
        :rtype: Any
        """
        if isinstance(data, dict):
            if "interval_every" in data and "interval_period" in data:
                data["interval"] = {
                    "every": data["interval_every"],
                    "period": data["interval_period"],
                }
                data["crontab"] = None
            elif "cron_expression" in data and "cron_timezone" in data:
                minute, hour, day_of_month, month_of_year, day_of_week = data[
                    "cron_expression"
                ].split()
                data["crontab"] = {
                    "timezone": data["cron_timezone"],
                    "minute": minute,
                    "hour": hour,
                    "day_of_month": day_of_month,
                    "month_of_year": month_of_year,
                    "day_of_week": day_of_week,
                }
                data["interval"] = None
            execute_request_data = {}
            for key, value in list(data.items()):
                if key.startswith("execute_request_"):
                    execute_request_data[key.replace("execute_request_", "")] = value
            if execute_request_data:
                data["execute_request"] = PeriodicTaskExecuteRequest(
                    **execute_request_data
                )
        return data


class PeriodicTaskCreateRequest(PeriodicTaskRequest):
    """Define the model for creating periodic tasks from the SEP app.

    Every field except 'task' defaults to None and only fields that were set are sent
    to the Tasks API.

    :param start_time: The start time for the task execution.
    :type start_time: UTCDatetime | EmptyStrToNone
    :param enabled: Whether the task is enabled.
    :type enabled: bool | EmptyStrToNone
    :param execute_request: The execution request details for the task.
    :type execute_request: PeriodicTaskExecuteRequest | EmptyStrToNone
    :param interval: The interval schedule for the task.
    :type interval: IntervalSchedule | EmptyStrToNone
    :param crontab: The crontab schedule for the task.
    :type crontab: CrontabSchedule | EmptyStrToNone
    :param task: The SEP task name.
    :type task: str
    """

    task: str


class EnhancedPeriodicTaskCreateRequest(PeriodicTaskCreateRequest):
    """Define a model for creating periodic tasks compatible with the SEP app form data.

    This model accepts keys prefixed with 'execute_request_' from form data, which are
    parsed by the base class into an execute_request object.

    :param start_time: The start time for the task execution.
    :type start_time: UTCDatetime | EmptyStrToNone
    :param enabled: Whether the task is enabled.
    :type enabled: bool | EmptyStrToNone
    :param execute_request: The execution request details for the task.
    :type execute_request: PeriodicTaskExecuteRequest | EmptyStrToNone
    :param interval: The interval schedule for the task.
    :type interval: IntervalSchedule | EmptyStrToNone
    :param crontab: The crontab schedule for the task.
    :type crontab: CrontabSchedule | EmptyStrToNone
    :param task: The SEP task name.
    :type task: str
    """
