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

"""Provide pure form-field parsing helpers shared across SEP UI code."""

from typing import Any


def parse_interval_form_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Build the structured ``interval`` dict from flat ``interval_*`` form fields.

    :param data: The raw form input. Must contain ``interval_every`` and
        ``interval_period``.
    :type data: dict[str, Any]
    :return: A dict with ``every`` and ``period`` keys ready to feed
        :class:`IntervalSchedule`.
    :rtype: dict[str, Any]
    """
    return {
        "every": data["interval_every"],
        "period": data["interval_period"],
    }


def parse_crontab_form_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Build the structured ``crontab`` dict from flat ``cron_*`` form fields.

    Split the 5-field ``cron_expression`` into named components and combine with
    ``cron_timezone``.

    :param data: The raw form input. Must contain ``cron_expression`` (5 space-
        separated fields) and ``cron_timezone``.
    :type data: dict[str, Any]
    :return: A dict ready to feed :class:`CrontabSchedule`.
    :rtype: dict[str, Any]
    """
    minute, hour, day_of_month, month_of_year, day_of_week = data[
        "cron_expression"
    ].split()
    return {
        "timezone": data["cron_timezone"],
        "minute": minute,
        "hour": hour,
        "day_of_month": day_of_month,
        "month_of_year": month_of_year,
        "day_of_week": day_of_week,
    }
