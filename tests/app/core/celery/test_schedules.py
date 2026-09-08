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

"""Define test cases for beat-faithful schedule time computation."""

from datetime import datetime, timedelta, UTC
from itertools import pairwise

import pytest
from celery import Celery
from sqlalchemy_celery_beat import tzcrontab
from sqlalchemy_celery_beat.models import Period
from sqlalchemy_celery_beat.schedulers import ModelEntry

from app.core.celery.models import CrontabSchedule, IntervalSchedule
from app.core.celery.schedules import (
    celery_schedule,
    INTERVAL_TIMEZONE,
    next_run_times,
    NEXT_RUNS_PREVIEW_COUNT,
    schedule_timezone,
)

#: A fixed "now" every expectation below is stated against.
NOW = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


class _DuckModel:
    """Stand in for a beat ``PeriodicTask`` row for a real ``ModelEntry``.

    ``ModelEntry`` reads its model duck-typed, so the contract test can build one
    from a SEP schedule without a database, a Session, or a stored row.
    """

    def __init__(self, schedule, start_time, last_run_at):
        """Carry the attributes ``ModelEntry.__init__`` and ``.is_due`` read.

        :param schedule: The celery schedule object beat consults.
        :param start_time: The earliest time the schedule may fire, if any.
        :param last_run_at: When the schedule last fired, if ever.
        """
        self.name = "contract"
        self.task = "app.tasks.celery.execute_task_by_name"
        self.schedule = schedule
        self.args = "[]"
        self.kwargs = "{}"
        self.headers = "{}"
        self.queue = self.exchange = self.routing_key = self.priority = None
        self.expires_ = None
        self.total_run_count = 0
        self.enabled = True
        self.one_off = False
        self.start_time = start_time
        self.last_run_at = last_run_at


def _freeze_library_clock(monkeypatch, moment):
    """Make the library's own clock read ``moment`` everywhere it looks.

    ``TzAwareCrontab.nowfunc`` builds its reading from
    ``tzcrontab.dt.datetime.now`` and normalises it into the crontab's zone, and
    ``ModelEntry`` reads ``_default_now`` in ``__init__`` for the back-date and
    again in ``is_due`` for the ``start_time`` gate. Freezing the *source* rather
    than overriding ``nowfun`` is what keeps the oracle independent: the
    conversion under test is performed by the library, not restated by the test.

    :param monkeypatch: The fixture used to install the frozen clock.
    :param moment: The instant the library should read as "now".
    """

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            """Report the frozen instant.

            :param tz: The zone to express the instant in.
            :return: ``moment``, converted to ``tz`` when one is given.
            """
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

    monkeypatch.setattr(tzcrontab.dt, "datetime", _FrozenDatetime)
    monkeypatch.setattr(ModelEntry, "_default_now", lambda _self: moment)


def _beat_first_run(interval, crontab, start_time, last_run_at, now, monkeypatch):
    """Return the first fire time a real ``ModelEntry`` reports for a schedule.

    Evaluated at ``start_time`` when that is still in the future, because before
    it ``ModelEntry.is_due`` returns a *re-check delay* rather than a fire time.
    Reading that delay as a fire time is the mistake this oracle exists to rule
    out.

    :param interval: The interval schedule, or ``None`` for a crontab schedule.
    :param crontab: The crontab schedule, or ``None`` for an interval schedule.
    :param start_time: The earliest time the schedule may fire, if any.
    :param last_run_at: When the schedule last fired, if ever.
    :param now: The instant to evaluate the entry at.
    :param monkeypatch: Used to freeze the library's clock.
    :return: The instant the entry reports as its next fire time.
    """
    cursor = start_time if start_time is not None and now < start_time else now
    _freeze_library_clock(monkeypatch, cursor)
    schedule = celery_schedule(interval, crontab)
    if not isinstance(schedule, tzcrontab.TzAwareCrontab):
        # An interval schedule reads the Celery app's clock, which freezing
        # ``tzcrontab`` does not reach, and uses it as an absolute instant with
        # no conversion, so pinning it restates nothing under test. A crontab is
        # left alone so its own ``nowfunc`` performs the conversion under test.
        schedule.nowfun = lambda: cursor
    model = _DuckModel(schedule, start_time, last_run_at)
    entry = ModelEntry(model, Session=None, app=Celery())
    due, delay = entry.is_due()
    return cursor if due else cursor + timedelta(seconds=delay)


class TestNextRunTimes:
    """Cover the fire times reported for a schedule."""

    def test_crontab_intersects_day_of_month_and_day_of_week(self):
        """Assert a dom-and-dow expression takes the scheduler's intersection.

        croniter unions the two restricted fields and would report 2026-09-01;
        beat intersects them and fires four months later.
        """
        crontab = CrontabSchedule(
            minute="0", hour="2", day_of_month="1", day_of_week="5"
        )
        runs = next_run_times(interval=None, crontab=crontab, now=NOW)
        assert runs == [
            datetime(2027, 1, 1, 2, 0, tzinfo=UTC),
            datetime(2027, 10, 1, 2, 0, tzinfo=UTC),
            datetime(2028, 9, 1, 2, 0, tzinfo=UTC),
        ]

    def test_crontab_resolves_a_skipped_local_time_the_scheduler_s_way(self):
        """Assert a spring-forward gap resolves the way beat resolves it.

        02:30 does not exist in Europe/Berlin on 2027-03-28. croniter reports
        03:00+02:00 (01:00Z); beat reports 02:30+01:00 (01:30Z).
        """
        crontab = CrontabSchedule(minute="30", hour="2", timezone="Europe/Berlin")
        runs = next_run_times(
            interval=None,
            crontab=crontab,
            now=datetime(2027, 3, 27, 12, 0, tzinfo=UTC),
            count=1,
        )
        assert runs == [datetime(2027, 3, 28, 1, 30, tzinfo=UTC)]

    def test_interval_with_future_start_time_first_fires_at_start_time(self):
        """Assert the back-date lands an unrun schedule's first run at start_time."""
        interval = IntervalSchedule(every=30, period=Period.MINUTES)
        start = NOW + timedelta(days=7)
        runs = next_run_times(
            interval=interval, crontab=None, start_time=start, now=NOW
        )
        assert runs == [
            start,
            start + timedelta(minutes=30),
            start + timedelta(minutes=60),
        ]

    def test_crontab_with_future_start_time_first_fires_at_start_time(self):
        """Assert a cron schedule previews no run before a future start_time."""
        crontab = CrontabSchedule(minute="0", hour="2")
        start = NOW + timedelta(days=7)
        runs = next_run_times(interval=None, crontab=crontab, start_time=start, now=NOW)
        assert runs[0] == start
        assert all(run >= start for run in runs)

    def test_interval_with_last_run_at_before_a_future_start_time(self):
        """Assert a set last_run_at suppresses the back-date.

        With ``last_run_at`` five minutes before ``start_time``, no back-date
        applies and the schedule is consulted normally at ``start_time``, so the
        first run is 25 minutes later, not ``start_time`` itself.
        """
        interval = IntervalSchedule(every=30, period=Period.MINUTES)
        start = NOW + timedelta(days=7)
        runs = next_run_times(
            interval=interval,
            crontab=None,
            start_time=start,
            last_run_at=start - timedelta(minutes=5),
            now=NOW,
            count=1,
        )
        assert runs == [start + timedelta(minutes=25)]

    def test_interval_with_long_past_last_run_at_fires_now(self):
        """Assert a schedule with missed runs fires immediately, not in the past."""
        interval = IntervalSchedule(every=5, period=Period.HOURS)
        runs = next_run_times(
            interval=interval,
            crontab=None,
            last_run_at=NOW - timedelta(days=180),
            now=NOW,
            count=2,
        )
        assert runs == [NOW, NOW + timedelta(hours=5)]

    def test_interval_without_start_time_counts_from_now(self):
        """Assert a never-run schedule with no start_time fires one interval out."""
        interval = IntervalSchedule(every=2, period=Period.DAYS)
        runs = next_run_times(interval=interval, crontab=None, now=NOW)
        assert runs == [
            NOW + timedelta(days=2),
            NOW + timedelta(days=4),
            NOW + timedelta(days=6),
        ]

    def test_disabled_schedule_has_no_runs(self):
        """Assert a disabled schedule reports an empty list, not None."""
        interval = IntervalSchedule(every=1, period=Period.HOURS)
        assert (
            next_run_times(interval=interval, crontab=None, enabled=False, now=NOW)
            == []
        )

    def test_disabled_schedule_with_an_unbuildable_cadence_has_no_runs(self):
        """Assert a disabled schedule short-circuits before its cadence is built.

        ``every=2_000_000_000`` days can't even be expressed as a
        ``timedelta``, so the disabled check has to run before
        ``celery_schedule`` does, or this raises ``OverflowError`` instead of
        honoring the empty-list contract.
        """
        interval = IntervalSchedule(every=2_000_000_000, period=Period.DAYS)
        assert (
            next_run_times(interval=interval, crontab=None, enabled=False, now=NOW)
            == []
        )

    def test_runs_are_strictly_increasing_utc(self):
        """Assert the reported runs advance and are all UTC."""
        crontab = CrontabSchedule(minute="0", hour="*/1", timezone="Asia/Tokyo")
        runs = next_run_times(interval=None, crontab=crontab, now=NOW)
        assert len(runs) == NEXT_RUNS_PREVIEW_COUNT
        assert runs == sorted(runs)
        assert len(set(runs)) == NEXT_RUNS_PREVIEW_COUNT
        assert [run.tzinfo for run in runs] == [UTC] * NEXT_RUNS_PREVIEW_COUNT

    def test_a_far_future_start_time_is_reported_faithfully(self):
        """Assert a distant start_time is reported rather than clamped."""
        interval = IntervalSchedule(every=1, period=Period.HOURS)
        start = NOW + timedelta(days=365 * 5)
        runs = next_run_times(
            interval=interval, crontab=None, start_time=start, now=NOW, count=1
        )
        assert runs == [start]

    def test_rejects_a_schedule_with_neither_kind_set(self):
        """Assert a schedule naming no cadence is refused."""
        with pytest.raises(ValueError, match="must be set"):
            next_run_times(interval=None, crontab=None, now=NOW)

    @pytest.mark.parametrize(
        "timezone", ["Asia/Tokyo", "America/New_York", "Pacific/Kiritimati", "UTC"]
    )
    def test_sub_hourly_crontab_keeps_its_cadence_in_every_zone(self, timezone):
        """Assert a sub-hourly expression stays sub-hourly away from UTC.

        The clock handed to the schedule has to be expressed in the schedule's
        own zone. Read as UTC, ``crontab.remaining_delta`` compares it against an
        already-converted ``last_run_at``, decides the two are on different days,
        and reports the next *hour* instead of the next ten minutes.
        """
        crontab = CrontabSchedule(minute="*/10", timezone=timezone)
        # 20:00Z is the next calendar day in Tokyo and Kiritimati, and the
        # previous one in New York, so each zone exercises a different sign of
        # the date disagreement.
        evaluated_at = datetime(2026, 9, 7, 20, 0, tzinfo=UTC)
        runs = next_run_times(
            interval=None,
            crontab=crontab,
            last_run_at=evaluated_at - timedelta(minutes=1),
            now=evaluated_at,
            count=3,
        )
        assert len(runs) == NEXT_RUNS_PREVIEW_COUNT
        assert {second - first for first, second in pairwise(runs)} == {
            timedelta(minutes=10)
        }


class TestScheduleTimezone:
    """Cover the zone reported for a schedule."""

    def test_interval_is_always_utc(self):
        """Assert an interval reports UTC regardless of start_time."""
        interval = IntervalSchedule(every=2, period=Period.DAYS)
        assert schedule_timezone(interval, None) == INTERVAL_TIMEZONE

    def test_crontab_reports_its_own_zone(self):
        """Assert a crontab reports the zone it is defined in."""
        crontab = CrontabSchedule(minute="0", hour="2", timezone="Europe/Lisbon")
        assert schedule_timezone(None, crontab) == "Europe/Lisbon"

    def test_rejects_a_schedule_with_neither_kind_set(self):
        """Assert a schedule naming no cadence is refused."""
        with pytest.raises(ValueError, match="must be set"):
            schedule_timezone(None, None)


class TestAgreesWithModelEntry:
    """Pin the mirrored ``ModelEntry`` rules against the library itself.

    ``next_run_times`` reimplements the ``start_time`` gate and the 30-year
    back-date because ``ModelEntry`` cannot yield a sequence of future runs.
    This matrix is what catches the library changing either rule under us.

    Its reach stops at the **first** run, which is all a ``ModelEntry`` can
    report. An overdue schedule is due at ``now`` in every zone, so agreement
    here says nothing about the clock the schedule is evaluated on;
    :meth:`TestNextRunTimes.test_sub_hourly_crontab_keeps_its_cadence_in_every_zone`
    is what covers that, by asserting the spacing between successive runs.
    """

    @pytest.mark.parametrize(
        ("interval", "crontab"),
        [
            (IntervalSchedule(every=30, period=Period.MINUTES), None),
            (IntervalSchedule(every=2, period=Period.DAYS), None),
            (None, CrontabSchedule(minute="0", hour="2")),
            (None, CrontabSchedule(minute="*/15")),
            (
                None,
                CrontabSchedule(
                    minute="0", hour="2", day_of_month="1", day_of_week="5"
                ),
            ),
            (None, CrontabSchedule(minute="30", hour="2", timezone="Europe/Berlin")),
            (None, CrontabSchedule(minute="*/10", timezone="Asia/Tokyo")),
            (None, CrontabSchedule(minute="*/15", timezone="America/New_York")),
        ],
        ids=[
            "every-30m",
            "every-2d",
            "nightly",
            "quarter-hourly",
            "dom-dow",
            "berlin",
            "sub-hourly-tokyo",
            "sub-hourly-new-york",
        ],
    )
    @pytest.mark.parametrize(
        "start_offset",
        [None, timedelta(days=-7), timedelta(days=7)],
        ids=["no-start", "past-start", "future-start"],
    )
    @pytest.mark.parametrize(
        "last_run_offset",
        [None, timedelta(minutes=-5), timedelta(days=-180)],
        ids=["never-run", "recent-run", "long-past-run"],
    )
    def test_first_run_matches_the_library(
        self, interval, crontab, start_offset, last_run_offset, monkeypatch
    ):
        """Assert the helper's first run is the one a real ModelEntry reports."""
        start_time = None if start_offset is None else NOW + start_offset
        last_run_at = None if last_run_offset is None else NOW + last_run_offset

        ours = next_run_times(
            interval=interval,
            crontab=crontab,
            start_time=start_time,
            last_run_at=last_run_at,
            now=NOW,
            count=1,
        )
        theirs = _beat_first_run(
            interval, crontab, start_time, last_run_at, NOW, monkeypatch
        )

        assert ours == [theirs.astimezone(UTC)]
