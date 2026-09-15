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

"""Define tests for seeding periodic tasks through ``init_periodic_tasks_db``.

Drive the shared seeding helper against an in-memory celery-beat database and
assert on the persisted row rather than the object the helper staged: the
``due_on_first_seed`` marker exists precisely because a value that is only ever
held in memory is lost before beat reads it.

The three closing cases assert due-ness against the library instead of a column,
and build their :class:`~sqlalchemy_celery_beat.models.PeriodicTask` in memory
because :class:`~sqlalchemy_celery_beat.schedulers.ModelEntry` resolves
``schedule_model`` eagerly, which raises ``MissingGreenlet`` against the async
``beat_maker`` harness the other cases use.
"""

from datetime import datetime, timedelta, UTC

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy_celery_beat.models import IntervalSchedule, Period, PeriodicTask
from sqlalchemy_celery_beat.schedulers import ModelEntry

from app.celery import celery
from app.core.celery import utils as celery_utils
from app.core.celery.crud import BasePeriodicTaskManager
from app.core.celery.models import CrontabSchedule as CrontabScheduleOption
from app.core.celery.models import IntervalSchedule as IntervalScheduleOption
from app.core.celery.utils import (
    init_periodic_tasks_db,
    SystemPeriodicTaskData,
    SystemPeriodicTaskSchedule,
)
from app.core.utils.date_time import make_datetime_utc, utc_now

SEEDED_PREFIX = "test__"
MARKED_NAME = f"{SEEDED_PREFIX}marked"
PLAIN_NAME = f"{SEEDED_PREFIX}plain"
TASK_NAME = "app.tasks.celery.execute_task_by_name"
FIFTEEN_MINUTES = IntervalScheduleOption(every=15, period=Period.MINUTES)


@pytest.fixture(name="seeding_against_beat_db")
def seeding_against_beat_db_fixture(mocker, beat_maker) -> None:
    """Point the helper's own session-maker binding at the in-memory beat DB."""
    mocker.patch.object(
        celery_utils, "get_async_session_maker", return_value=beat_maker
    )


def _schedule(*tasks: SystemPeriodicTaskData) -> list[SystemPeriodicTaskSchedule]:
    """Wrap tasks in the fifteen-minute interval schedule the helper expects."""
    return [SystemPeriodicTaskSchedule(schedule=FIFTEEN_MINUTES, tasks=list(tasks))]


async def _stamp(
    beat_maker: async_sessionmaker[AsyncSession], **fields: datetime
) -> None:
    """Write timing fields onto the seeded row, standing in for beat or an operator."""
    async with beat_maker() as session:
        row = await BasePeriodicTaskManager.first(session, name=MARKED_NAME)
        assert row is not None
        for field, value in fields.items():
            setattr(row, field, value)
        session.add(row)
        await session.commit()


async def _row(
    beat_maker: async_sessionmaker[AsyncSession], name: str = MARKED_NAME
) -> PeriodicTask:
    """Re-read a seeded row in a fresh session, so only persisted state is seen."""
    async with beat_maker() as session:
        row = await BasePeriodicTaskManager.first(session, name=name)
    assert row is not None
    return row


@pytest.mark.asyncio
@pytest.mark.usefixtures("seeding_against_beat_db")
async def test_opting_in_marks_a_new_row_due(beat_maker) -> None:
    """Assert an opted-in row is persisted with a past start time and no run time."""
    before = utc_now()

    await init_periodic_tasks_db(
        _schedule(
            SystemPeriodicTaskData(
                name=MARKED_NAME, task_name=TASK_NAME, due_on_first_seed=True
            )
        ),
        SEEDED_PREFIX,
    )

    row = await _row(beat_maker)
    assert row.start_time is not None
    assert before <= make_datetime_utc(row.start_time) <= utc_now()
    assert row.last_run_at is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("seeding_against_beat_db")
async def test_not_opting_in_leaves_a_new_row_unmarked(beat_maker) -> None:
    """Assert a row that does not opt in keeps today's unmarked timing."""
    await init_periodic_tasks_db(
        _schedule(SystemPeriodicTaskData(name=MARKED_NAME, task_name=TASK_NAME)),
        SEEDED_PREFIX,
    )

    row = await _row(beat_maker)
    assert row.start_time is None
    assert row.last_run_at is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("seeding_against_beat_db")
async def test_reseeding_does_not_rewrite_the_marker(beat_maker) -> None:
    """Assert a second seed leaves an operator's own start time in place."""
    tasks = _schedule(
        SystemPeriodicTaskData(
            name=MARKED_NAME, task_name=TASK_NAME, due_on_first_seed=True
        )
    )
    await init_periodic_tasks_db(tasks, SEEDED_PREFIX)
    operator_start_time = datetime(2026, 1, 1, tzinfo=UTC)
    await _stamp(beat_maker, start_time=operator_start_time)

    await init_periodic_tasks_db(tasks, SEEDED_PREFIX)

    row = await _row(beat_maker)
    assert row.start_time is not None
    assert make_datetime_utc(row.start_time) == operator_start_time


@pytest.mark.asyncio
@pytest.mark.usefixtures("seeding_against_beat_db")
async def test_reseeding_does_not_write_the_last_run_time(beat_maker) -> None:
    """Assert a second seed preserves the run time beat recorded on dispatch."""
    tasks = _schedule(
        SystemPeriodicTaskData(
            name=MARKED_NAME, task_name=TASK_NAME, due_on_first_seed=True
        )
    )
    await init_periodic_tasks_db(tasks, SEEDED_PREFIX)
    dispatched_at = utc_now()
    await _stamp(beat_maker, last_run_at=dispatched_at)

    await init_periodic_tasks_db(tasks, SEEDED_PREFIX)

    row = await _row(beat_maker)
    assert row.last_run_at is not None
    assert make_datetime_utc(row.last_run_at) == dispatched_at


@pytest.mark.asyncio
@pytest.mark.usefixtures("seeding_against_beat_db")
async def test_opting_in_marks_a_crontab_row(beat_maker) -> None:
    """Assert the marker carries no interval arithmetic, so crontab rows take it."""
    await init_periodic_tasks_db(
        [
            SystemPeriodicTaskSchedule(
                schedule=CrontabScheduleOption(minute="0", hour="3"),
                tasks=[
                    SystemPeriodicTaskData(
                        name=MARKED_NAME, task_name=TASK_NAME, due_on_first_seed=True
                    )
                ],
            )
        ],
        SEEDED_PREFIX,
    )

    row = await _row(beat_maker)
    assert row.start_time is not None


@pytest.mark.asyncio
@pytest.mark.usefixtures("seeding_against_beat_db")
async def test_only_the_opted_in_sibling_is_marked(beat_maker) -> None:
    """Assert sharing one schedule does not spread the marker between entries."""
    await init_periodic_tasks_db(
        _schedule(
            SystemPeriodicTaskData(
                name=MARKED_NAME, task_name=TASK_NAME, due_on_first_seed=True
            ),
            SystemPeriodicTaskData(name=PLAIN_NAME, task_name=TASK_NAME),
        ),
        SEEDED_PREFIX,
    )

    assert (await _row(beat_maker, MARKED_NAME)).start_time is not None
    assert (await _row(beat_maker, PLAIN_NAME)).start_time is None


def _entry(last_run_at: datetime | None) -> ModelEntry:
    """Build a beat entry over a marked, in-memory fifteen-minute schedule.

    The session factory is never exercised: ``is_due`` reads it only on the
    disable paths, which an enabled, non-one-off row does not take.

    :param last_run_at: The dispatch time to present, or ``None`` for a row beat
        has never fired.
    :return: The entry beat would build for such a row.
    """
    task = PeriodicTask(
        name=MARKED_NAME,
        task=TASK_NAME,
        schedule_model=IntervalSchedule(every=15, period=Period.MINUTES),
        start_time=utc_now(),
        last_run_at=last_run_at,
        enabled=True,
        one_off=False,
        total_run_count=0,
    )
    return ModelEntry(task, Session=sessionmaker(), app=celery)


def test_the_marker_makes_an_entry_due() -> None:
    """Assert a marked row beat has never dispatched is due on its first load."""
    assert _entry(last_run_at=None).is_due().is_due is True


def test_a_dispatched_row_is_not_due_again() -> None:
    """Assert the interval debounce still governs once beat has dispatched."""
    assert _entry(last_run_at=utc_now()).is_due().is_due is False


def test_a_row_dispatched_long_ago_is_due_exactly_once() -> None:
    """Assert an outage longer than the interval dispatches once, not per interval."""
    entry = _entry(last_run_at=utc_now() - timedelta(hours=3))

    due, next_check = entry.is_due()

    assert due is True
    assert next_check == timedelta(minutes=15).total_seconds()
