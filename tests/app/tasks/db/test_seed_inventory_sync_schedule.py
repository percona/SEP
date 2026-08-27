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

"""Define tests for seeding the default inventory-sync schedule.

Drive :func:`app.tasks.db.seed.seed_system_periodic_tasks` against an in-memory
celery-beat database. Both session-maker seams are redirected to the same maker:
``init_periodic_tasks_db`` resolves its own module binding while the pre-seed
lookup resolves ``app.tasks.db.seed``'s alias, so patching only one would leave
the read path and the write path on different databases.
"""

import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy_celery_beat.models import IntervalSchedule, Period, PeriodicTask
from sqlmodel import SQLModel

import app.tasks.db.seed as seed_module
from app.core.celery import utils as celery_utils
from app.core.celery.crud import BasePeriodicTaskManager
from app.core.celery.models import IntervalSchedule as IntervalScheduleOption
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.tasks.config import tasks_settings
from app.tasks.models import INVENTORY_SYNC_TASK_NAME
from tests.app.db_schema import apply_schema

PMM_SYNCER = "app.sep.sync.syncers.pmm.PMMSyncer"
MYSQL_SYNCER = "app.sep.sync.syncers.mysql.syncer.MySQLSyncer"
FIFTEEN_MINUTES = IntervalScheduleOption(every=15, period=Period.MINUTES)
OPERATOR_TASK_NAME = "run_inventory-sync_15_minutes"


@pytest_asyncio.fixture(name="beat_maker")
async def beat_maker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Provide a session maker bound to an in-memory celery-beat DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"celery_schema": None})
    async with engine.begin() as conn:
        await apply_schema(conn, PeriodicTask.__table__.metadata)
    try:
        yield get_async_session_maker_from_engine(engine)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(name="tasks_maker")
async def tasks_maker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Provide a session maker bound to an in-memory tasks DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await apply_schema(conn, SQLModel.metadata)
    try:
        yield get_async_session_maker_from_engine(engine)
    finally:
        await engine.dispose()


@pytest.fixture(name="configured")
def configured_fixture(mocker, beat_maker) -> None:
    """Pin both session-maker seams and the PMM-targeted default settings."""
    mocker.patch.object(
        celery_utils, "get_async_session_maker", return_value=beat_maker
    )
    mocker.patch.object(
        seed_module, "get_celery_beat_session_maker", return_value=beat_maker
    )
    mocker.patch.object(tasks_settings, "INVENTORY_SYNC_INTERVAL", FIFTEEN_MINUTES)
    mocker.patch.object(tasks_settings, "INVENTORY_SYNC_SYNCER", PMM_SYNCER)


async def _insert_operator_row(
    session: AsyncSession,
    kwargs: str | None,
    *,
    name: str = OPERATOR_TASK_NAME,
    enabled: bool = True,
) -> None:
    """Insert a beat row shaped like one the operator attached through the API."""
    schedule = IntervalSchedule(every=15, period=Period.MINUTES)
    session.add(schedule)
    await session.flush()
    session.add(
        PeriodicTask(
            name=name,
            task="app.tasks.celery.execute_task_by_name",
            schedule_model=schedule,
            kwargs=kwargs,
            enabled=enabled,
        )
    )
    await session.commit()


def _operator_kwargs(syncer: str | None = None) -> str:
    """Build the ``kwargs`` payload an operator-created schedule carries."""
    return json.dumps(
        {
            "task_name": INVENTORY_SYNC_TASK_NAME,
            "periodic_task_name": OPERATOR_TASK_NAME,
            **({"execution_data": {"meta": {"syncer": syncer}}} if syncer else {}),
        }
    )


async def _seeded_rows(
    beat_maker: async_sessionmaker[AsyncSession],
) -> list[PeriodicTask]:
    """Return the beat rows carrying the seeded inventory-sync schedule name."""
    async with beat_maker() as session:
        return await BasePeriodicTaskManager.list(
            session, name=seed_module.INVENTORY_SYNC_SCHEDULE_NAME
        )


@pytest.mark.asyncio
async def test_fresh_seed_creates_the_pinned_schedule(configured, beat_maker) -> None:
    """Assert an empty beat store gets exactly one PMM-pinned schedule."""
    await seed_module.seed_system_periodic_tasks()

    (row,) = await _seeded_rows(beat_maker)
    assert row.task == "app.tasks.celery.execute_task_by_name"
    kwargs = json.loads(row.kwargs)
    assert kwargs["task_name"] == INVENTORY_SYNC_TASK_NAME
    assert kwargs["execution_data"]["meta"]["syncer"] == PMM_SYNCER
    assert (row.schedule_model.every, row.schedule_model.period) == (
        15,
        Period.MINUTES,
    )


@pytest.mark.asyncio
async def test_seeding_twice_is_idempotent(configured, beat_maker) -> None:
    """Assert the seeder does not read its own row as an operator schedule."""
    await seed_module.seed_system_periodic_tasks()
    (first,) = await _seeded_rows(beat_maker)

    await seed_module.seed_system_periodic_tasks()

    (second,) = await _seeded_rows(beat_maker)
    assert second.id == first.id


@pytest.mark.asyncio
@pytest.mark.parametrize("syncer", [PMM_SYNCER, None], ids=["pinned", "sync-all"])
async def test_operator_row_covering_the_syncer_blocks_the_default(
    configured, beat_maker, syncer: str | None
) -> None:
    """Assert an operator schedule covering PMM suppresses the seeded default."""
    async with beat_maker() as session:
        await _insert_operator_row(session, _operator_kwargs(syncer))

    await seed_module.seed_system_periodic_tasks()

    assert await _seeded_rows(beat_maker) == []
    async with beat_maker() as session:
        operator_row = await BasePeriodicTaskManager.first(
            session, name=OPERATOR_TASK_NAME
        )
    assert operator_row is not None
    assert json.loads(operator_row.kwargs) == json.loads(_operator_kwargs(syncer))


@pytest.mark.asyncio
async def test_operator_row_for_another_syncer_does_not_block(
    configured, beat_maker
) -> None:
    """Assert a MySQL-pinned operator schedule leaves the PMM default seeded."""
    async with beat_maker() as session:
        await _insert_operator_row(session, _operator_kwargs(MYSQL_SYNCER))

    await seed_module.seed_system_periodic_tasks()

    assert len(await _seeded_rows(beat_maker)) == 1
    async with beat_maker() as session:
        operator_row = await BasePeriodicTaskManager.first(
            session, name=OPERATOR_TASK_NAME
        )
    assert operator_row is not None
    assert json.loads(operator_row.kwargs)["execution_data"]["meta"]["syncer"] == (
        MYSQL_SYNCER
    )


@pytest.mark.asyncio
async def test_disabled_operator_row_blocks_the_default(configured, beat_maker) -> None:
    """Assert a paused operator schedule is honoured rather than resumed."""
    async with beat_maker() as session:
        await _insert_operator_row(session, _operator_kwargs(PMM_SYNCER), enabled=False)

    await seed_module.seed_system_periodic_tasks()

    assert await _seeded_rows(beat_maker) == []


@pytest.mark.asyncio
async def test_operator_attaching_after_upgrade_converges_to_one_row(
    configured, beat_maker
) -> None:
    """Assert a post-upgrade operator schedule replaces the seeded default."""
    await seed_module.seed_system_periodic_tasks()
    async with beat_maker() as session:
        await _insert_operator_row(session, _operator_kwargs(PMM_SYNCER))

    await seed_module.seed_system_periodic_tasks()

    assert await _seeded_rows(beat_maker) == []
    async with beat_maker() as session:
        operator_row = await BasePeriodicTaskManager.first(
            session, name=OPERATOR_TASK_NAME
        )
    assert operator_row is not None


@pytest.mark.asyncio
async def test_unsetting_the_interval_removes_a_seeded_row(
    configured, mocker, beat_maker
) -> None:
    """Assert clearing INVENTORY_SYNC_INTERVAL removes the seeded schedule."""
    await seed_module.seed_system_periodic_tasks()
    mocker.patch.object(tasks_settings, "INVENTORY_SYNC_INTERVAL", None)

    await seed_module.seed_system_periodic_tasks()

    assert await _seeded_rows(beat_maker) == []


@pytest.mark.asyncio
async def test_disabling_the_seeded_row_survives_a_reseed(
    configured, beat_maker
) -> None:
    """Assert an operator-disabled seeded schedule is not silently resumed."""
    await seed_module.seed_system_periodic_tasks()
    async with beat_maker() as session:
        row = await BasePeriodicTaskManager.first(
            session, name=seed_module.INVENTORY_SYNC_SCHEDULE_NAME
        )
        row.enabled = False
        session.add(row)
        await session.commit()

    await seed_module.seed_system_periodic_tasks()

    (row,) = await _seeded_rows(beat_maker)
    assert row.enabled is False


@pytest.mark.asyncio
async def test_malformed_operator_kwargs_fails_closed(configured, beat_maker) -> None:
    """Assert an undecodable operator row neither breaks boot nor double-schedules."""
    async with beat_maker() as session:
        await _insert_operator_row(session, "{not json")

    await seed_module.seed_system_periodic_tasks()

    assert await _seeded_rows(beat_maker) == []


@pytest.mark.asyncio
async def test_unreadable_beat_store_skips_a_first_time_default(
    configured, mocker
) -> None:
    """Assert a failing pre-seed lookup skips the default instead of raising."""
    mocker.patch.object(
        seed_module.PeriodicTaskManager,
        "list_by_task_names",
        autospec=True,
        side_effect=SQLAlchemyError("beat store unreadable"),
    )

    assert await seed_module._default_inventory_sync_schedule() is None


@pytest.mark.asyncio
async def test_unreadable_beat_store_keeps_an_already_seeded_default(
    configured, beat_maker, mocker
) -> None:
    """Assert a failing lookup does not let the orphan cleanup drop the default.

    Omitting the entry is not neutral: ``init_periodic_tasks_db`` deletes every
    ``tasks__`` row it was not handed, so a data-level lookup failure would stop
    the sync on a deployment that was already syncing.
    """
    await seed_module.seed_system_periodic_tasks()
    mocker.patch.object(
        seed_module.PeriodicTaskManager,
        "list_by_task_names",
        autospec=True,
        side_effect=SQLAlchemyError("malformed persisted kwargs"),
    )

    await seed_module.seed_system_periodic_tasks()

    (row,) = await _seeded_rows(beat_maker)
    assert json.loads(row.kwargs)["execution_data"]["meta"]["syncer"] == PMM_SYNCER


@pytest.mark.asyncio
async def test_startup_seeds_the_schedule(configured, beat_maker, tasks_maker, mocker):
    """Assert startup itself provisions the schedule, not just the seeder.

    Every other test in this module drives ``seed_system_periodic_tasks``
    directly, so none of them would notice ``init_tasks_db`` losing the call.
    Both databases are real here: the tasks tables the system-task half writes,
    and the beat store the assertion reads.
    """
    mocker.patch.object(
        seed_module, "get_async_session_maker", return_value=tasks_maker
    )

    await seed_module.init_tasks_db()

    (row,) = await _seeded_rows(beat_maker)
    assert json.loads(row.kwargs)["execution_data"]["meta"]["syncer"] == PMM_SYNCER
