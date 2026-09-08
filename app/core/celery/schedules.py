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

"""Compute beat-faithful fire times for SEP's schedule models.

Every time reported here comes from the schedule object Celery beat itself
consults: ``celery.schedules.schedule`` for an interval,
``sqlalchemy_celery_beat.tzcrontab.TzAwareCrontab`` for a crontab. The API's
account of a schedule and the scheduler's behaviour therefore cannot drift
apart on a cron dialect or a DST transition.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, UTC
from typing import Final

from celery.schedules import BaseSchedule
from sqlalchemy_celery_beat import CrontabSchedule as BaseCrontabSchedule

from app.core.celery.models import CrontabSchedule, IntervalSchedule
from app.core.utils.date_time import utc_now

__all__ = [
    "INTERVAL_TIMEZONE",
    "NEXT_RUNS_PREVIEW_COUNT",
    "celery_schedule",
    "next_run_times",
    "schedule_timezone",
]

#: How far ``sqlalchemy_celery_beat.schedulers.ModelEntry.__init__`` back-dates
#: an unset ``last_run_at`` when ``start_time`` is set, so the first run lands
#: at ``start_time`` instead of one interval after it.
BEAT_BACKDATE: Final = timedelta(days=365 * 30)

#: How many upcoming runs a schedule preview reports.
NEXT_RUNS_PREVIEW_COUNT: Final = 3

#: The zone an interval schedule is defined in. An interval's cadence is an
#: absolute :class:`~datetime.timedelta` with no wall-clock anchor, so it has no
#: zone of its own and every timestamp SEP reports for it is UTC.
INTERVAL_TIMEZONE: Final = "UTC"


def _clock_reading(schedule: BaseSchedule, moment: datetime) -> Callable[[], datetime]:
    """Return a celery ``nowfun`` reporting ``moment`` on ``schedule``'s clock.

    Mirror ``TzAwareCrontab.nowfunc``, which reports the instant expressed in
    the schedule's own zone. ``crontab.remaining_delta`` compares calendar fields
    between that reading and a ``last_run_at`` that ``is_due`` has already
    converted, so a UTC-expressed reading makes the two disagree about the date
    whenever the zone's offset puts them on different days, and a sub-hourly
    expression then reports hourly runs.

    An interval schedule uses the reading as an absolute instant rather than by
    calendar field, so converting it there changes nothing.

    :param schedule: The schedule whose clock is being pinned.
    :param moment: The instant the returned callable reports as "now".
    :return: A zero-argument callable returning ``moment`` on that clock.
    """
    return lambda: moment.astimezone(schedule.tz)


def celery_schedule(
    interval: IntervalSchedule | None, crontab: CrontabSchedule | None
) -> BaseSchedule:
    """Return the celery schedule object beat consults for this schedule.

    :param interval: The interval schedule, or ``None`` for a crontab schedule.
    :param crontab: The crontab schedule, or ``None`` for an interval schedule.
    :return: The ``celery.schedules`` object beat evaluates to decide when the
        task fires.
    :raises ValueError: If neither schedule is set.
    :raises OverflowError: If an interval's cadence exceeds
        :class:`~datetime.timedelta`'s range.
    """
    if interval is not None:
        return interval.schedule
    if crontab is not None:
        return BaseCrontabSchedule.aware_crontab(crontab)
    raise ValueError("Either `interval` or `crontab` must be set.")


def schedule_timezone(
    interval: IntervalSchedule | None, crontab: CrontabSchedule | None
) -> str:
    """Return the zone the schedule is defined in.

    :param interval: The interval schedule, or ``None`` for a crontab schedule.
    :param crontab: The crontab schedule, or ``None`` for an interval schedule.
    :return: The crontab's own zone, or :data:`INTERVAL_TIMEZONE` for an
        interval schedule.
    :raises ValueError: If neither schedule is set.
    """
    if interval is not None:
        return INTERVAL_TIMEZONE
    if crontab is not None:
        return crontab.timezone
    raise ValueError("Either `interval` or `crontab` must be set.")


def next_run_times(
    *,
    interval: IntervalSchedule | None,
    crontab: CrontabSchedule | None,
    start_time: datetime | None = None,
    last_run_at: datetime | None = None,
    enabled: bool = True,
    now: datetime | None = None,
    count: int = NEXT_RUNS_PREVIEW_COUNT,
) -> list[datetime]:
    """Return the next ``count`` UTC times beat would fire this schedule.

    Mirror the two rules ``sqlalchemy_celery_beat.schedulers.ModelEntry``
    applies around the schedule object: an unset ``last_run_at`` is back-dated
    by :data:`BEAT_BACKDATE` when ``start_time`` is set, so the first run lands
    at ``start_time``; and no run is reported before ``start_time``.

    ``ModelEntry`` itself cannot produce the sequence. Iterating it re-anchors
    ``last_run_at`` to real now and yields the same fire time every time, and
    its failure paths need a ``Session``, so the rules are mirrored here rather
    than reused. ``ModelEntry``'s remaining behaviour is deliberately omitted:
    the ``one_off`` branch (SEP never sets the column), ``expires`` handling
    (SEP bounds dispatch, not the schedule), and disabling a schedule that fails
    to build (validation upstream makes it unreachable).

    An already-due schedule fires at ``now``, so the first run it reports is
    ``now`` itself; every later run is the next fire time after the one before
    it.

    :param interval: The interval schedule, or ``None`` for a crontab schedule.
    :param crontab: The crontab schedule, or ``None`` for an interval schedule.
    :param start_time: The earliest time the schedule may fire, if any.
    :param last_run_at: When the schedule last fired, if ever.
    :param enabled: Whether the schedule is enabled; a disabled schedule has no
        upcoming runs.
    :param now: The instant to evaluate from. Defaults to
        :func:`~app.core.utils.date_time.utc_now`.
    :param count: How many upcoming runs to return.
    :return: Up to ``count`` strictly increasing UTC datetimes, empty when the
        schedule is disabled.
    :raises ValueError: If neither ``interval`` nor ``crontab`` is set.
    :raises OverflowError: If the cadence or a computed run falls outside
        :class:`~datetime.datetime`'s range. The periodic-task write and preview
        models reject such a schedule at the request boundary.
    """
    if not enabled:
        return []
    schedule = celery_schedule(interval, crontab)
    now = now or utc_now()
    effective_last = last_run_at
    if effective_last is None:
        effective_last = now - BEAT_BACKDATE if start_time is not None else now
    cursor = start_time if start_time is not None and now < start_time else now
    runs: list[datetime] = []
    for _ in range(count):
        schedule.nowfun = _clock_reading(schedule, cursor)
        due, remaining = schedule.is_due(effective_last)
        upcoming = cursor if due and not runs else cursor + timedelta(seconds=remaining)
        if runs and upcoming <= runs[-1]:
            break
        runs.append(upcoming)
        effective_last = cursor = upcoming
    return [run.astimezone(UTC) for run in runs]
