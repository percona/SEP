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

"""Define models for Celery periodic tasks and schedules."""

from typing import Any
from zoneinfo import available_timezones

from pydantic import BaseModel, field_validator, model_validator, PositiveInt
from sqlalchemy_celery_beat import CrontabSchedule as BaseCrontabSchedule
from sqlalchemy_celery_beat.models import Period


class IntervalSchedule(BaseModel):
    """Represent an interval schedule.

    :param every: The number of periods between each execution.
    :type every: PositiveInt
    :param period: The period unit for the interval (e.g., hours, minutes).
    :type period: Period
    """

    every: PositiveInt
    period: Period

    @model_validator(mode="before")
    @classmethod
    def create_from_str(cls, data: Any) -> Any:
        """Create an IntervalSchedule instance from a string.

        Converts a string representation of an interval schedule into an
        `IntervalSchedule` instance.

        :param data: The input data containing the interval schedule.
        :type data: Any
        :return: The validated data.
        :rtype: Any
        """
        if isinstance(data, str):
            data = data.lower()
            data = data.removeprefix("every ")
            every, period = data.strip().split(maxsplit=1)
            return {
                "every": every,
                "period": period,
            }
        return data

    def __str__(self) -> str:
        """Return a string representation of the interval schedule.

        Formats the schedule as "every {every} {period}", handling singular forms
        appropriately.

        :return: A formatted string representing the interval schedule.
        :rtype: str
        """
        str_schedule = f"every {self.every} {self.period.value}"
        if self.every == 1:
            return str_schedule[:-1]
        return str_schedule


class CrontabSchedule(BaseModel):
    """Representing a crontab schedule.

    :param minute: Represents the minute component in cron format. Defaults to `"*"`.
    :type minute: str
    :param hour: Represents the hour component in cron format. Defaults to `"*"`.
    :type hour: str
    :param day_of_week: Represents the day of the week component in cron format.
        Defaults to `"*"`.
    :type day_of_week: str
    :param day_of_month: Represents the day of the month component in cron format.
        Defaults to `"*"`.
    :type day_of_month: str
    :param month_of_year: Represents the month component in cron format.
        Defaults to `"*"`.
    :type month_of_year: str
    :param timezone: The timezone for the cron schedule. Defaults to "UTC". Must be a
        valid timezone as returned in `available_timezones()`
    :type timezone: str
    """

    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"
    timezone: str = "UTC"

    def __str__(self) -> str:
        """Return a string representation of the crontab schedule.

        Formats the schedule according to cron expression standards and includes the
        timezone.

        :return: A formatted string representing the crontab schedule.
        :rtype: str
        """
        fmt_kwargs = {
            field: BaseCrontabSchedule.cronexp(value)
            for field, value in self.model_dump(exclude={"timezone"}).items()
        }
        return "{minute} {hour} {day_of_month} {month_of_year} {day_of_week}".format(
            **fmt_kwargs
        )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate the timezone field.

        Ensures that the provided timezone is among the available timezones.

        :param v: The timezone string to validate.
        :type v: str
        :return: The validated timezone string.
        :rtype: str
        :raises ValueError: If the timezone is not valid.
        """
        if v not in available_timezones():
            raise ValueError(f"{v} is not a valid timezone")
        return v
