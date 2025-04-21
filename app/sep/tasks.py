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
    :param expires: The expiration time for the task execution.
    :type expires: UTCDatetime | EmptyStrToNone
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
    expires: UTCDatetime | EmptyStrToNone = None
    enabled: bool | EmptyStrToNone = None
    execute_request: PeriodicTaskExecuteRequest | EmptyStrToNone = None
    interval: IntervalSchedule | EmptyStrToNone = None
    crontab: CrontabSchedule | EmptyStrToNone = None

    @model_validator(mode="before")
    @classmethod
    def set_period(cls, data: Any) -> Any:
        """Populate period (interval or crontab) data.

        Transforms the input form data into the interval/crontab format.

        :param data: The form input.
        :type data: Any
        :return: The modified data with appropriate interval/crontab fields.
        :rtype: Any
        """
        if isinstance(data, dict):
            if "interval_every" in data and "interval_period" in data:
                data["interval"] = {
                    "every": data["interval_every"],
                    "period": data["interval_period"],
                }
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
        return data


class PeriodicTaskCreateRequest(PeriodicTaskRequest):
    """Define the model for creating periodic tasks from the SEP app.

    Every field except 'task' defaults to None and only fields that were set are sent
    to the Tasks API.

    :param start_time: The start time for the task execution.
    :type start_time: UTCDatetime | EmptyStrToNone
    :param expires: The expiration time for the task execution.
    :type expires: UTCDatetime | EmptyStrToNone
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

    This model populates the execute_request field by extracting keys prefixed with 'execute_request_'
    and combines them into an ExecuteRequest object.

    :param start_time: The start time for the task execution.
    :type start_time: UTCDatetime | EmptyStrToNone
    :param expires: The expiration time for the task execution.
    :type expires: UTCDatetime | EmptyStrToNone
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

    @model_validator(mode="before")
    @classmethod
    def populate_execute_request(cls, data: Any) -> Any:
        """Populate the execute_request field by extracting keys prefixed with 'execute_request_'.

        :param data: The input data containing potential execute_request fields.
        :type data: Any
        :return: The modified data with the execute_request field populated.
        :rtype: Any
        """
        if isinstance(data, dict):
            execute_request_data = {}
            for key, value in list(data.items()):
                if key.startswith("execute_request_"):
                    execute_request_data[key.replace("execute_request_", "")] = value
            if execute_request_data:
                data["execute_request"] = PeriodicTaskExecuteRequest(
                    **execute_request_data
                )
        return data
