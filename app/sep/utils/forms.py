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

STANDARD_CRON_FIELD_COUNT = 5


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

    Checks that the ``cron_expression`` splits into the expected number of
    fields before naming them, so callers receive a clear error rather than a
    server fault. Whether the expression itself is one the scheduler can run is
    decided by :class:`~app.core.celery.models.CrontabSchedule`, the single
    parser both this form path and the JSON API path feed into.

    :param data: The raw form input. Must contain ``cron_expression`` (5 space-
        separated fields) and ``cron_timezone``.
    :return: A dict ready to feed :class:`CrontabSchedule`.
    :raises ValueError: If ``cron_expression`` is empty or has the wrong number
        of fields.
    """
    raw_expr = data["cron_expression"]
    cron_expression = str(raw_expr or "").strip()
    if not cron_expression:
        msg = "Invalid cron expression: expression is empty."
        raise ValueError(msg)
    parts = cron_expression.split()
    if len(parts) != STANDARD_CRON_FIELD_COUNT:
        msg = (
            "Invalid cron expression: expected "
            f"{STANDARD_CRON_FIELD_COUNT} whitespace-separated fields "
            "(minute hour day-of-month month day-of-week), got "
            f"{len(parts)}."
        )
        raise ValueError(msg)
    minute, hour, day_of_month, month_of_year, day_of_week = parts
    return {
        "timezone": data["cron_timezone"],
        "minute": minute,
        "hour": hour,
        "day_of_month": day_of_month,
        "month_of_year": month_of_year,
        "day_of_week": day_of_week,
    }
