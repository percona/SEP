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

"""Tests for AppState seeding in :func:`app.sep.db.seed.init_sep_db`."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy_celery_beat import IntervalSchedule
from sqlalchemy_celery_beat.models import Period, PeriodicTask
from sqlmodel import SQLModel

from app.core.celery.crud import BasePeriodicTaskManager
from app.core.celery.utils import SystemPeriodicTaskData, SystemPeriodicTaskSchedule
from app.core.config import settings
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.sep import periodic_tasks as periodic_tasks_module
from app.sep.apps.framework.registry import get_app_registry
from app.sep.config import App
from app.sep.crud import AppStateManager, SEPPluginPeriodicTaskManager
from app.sep.db import seed as seed_module
from app.sep.models import AppLifecycleEnum, AppState

SNIPPETS_TASK = "sep__sync_snippets"
CELERY_RESULT_EXPIRES_SECONDS = 3600


def _plugin(key: str, *, enabled: bool = True) -> App:
    """Build an ``App`` activation entry for ``key``."""
    return App(module_name=key, enabled=enabled)


@pytest.fixture(autouse=True)
def _clear_registry_cache() -> None:
    """Rebuild the registry from each test's patched ``APPS``."""
    get_app_registry.cache_clear()
    yield
    get_app_registry.cache_clear()


@pytest_asyncio.fixture(name="seed_maker")
async def seed_maker_fixture() -> AsyncIterator:
    """Provide a session maker bound to an in-memory SQLite DB with all tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield get_async_session_maker_from_engine(engine)


@pytest.fixture
def patched_seed(mocker, seed_maker):
    """Patch the seed module's session maker and stub the periodic-task work.

    Both the celery-beat task seeding (``init_periodic_tasks_db``) and the
    cross-database gating (``sync_app_periodic_task_gating``) are stubbed so the
    AppState-only tests never reach a real scheduler database.
    """
    mocker.patch.object(seed_module, "get_async_session_maker", return_value=seed_maker)
    mocker.patch.object(
        seed_module, "sync_app_periodic_task_gating", new_callable=mocker.AsyncMock
    )
    return mocker.patch.object(
        seed_module, "init_periodic_tasks_db", new_callable=mocker.AsyncMock
    )


@pytest.mark.asyncio
class TestInitSepDbAppStateSeeding:
    """Tests for the AppState portion of ``init_sep_db``."""

    async def test_first_run_inserts_rows_with_yaml_enabled(
        self, mocker, patched_seed, seed_maker
    ) -> None:
        """Each non-protected plugin yields a row with its YAML ``enabled`` value."""
        mocker.patch.object(
            seed_module.sep_settings,
            "APPS",
            [
                _plugin("snippets", enabled=True),
                _plugin("checksums", enabled=False),
                _plugin("inventory", enabled=True),
            ],
        )

        await seed_module.init_sep_db()

        async with seed_maker() as session:
            lifecycle_states = await AppStateManager.all_lifecycle_states(session)
        assert lifecycle_states == {
            "snippets": AppLifecycleEnum.ENABLED,
            "checksums": AppLifecycleEnum.DISABLED,
        }

    async def test_inventory_is_never_seeded(
        self, mocker, patched_seed, seed_maker
    ) -> None:
        """The protected ``inventory`` app gets no row even when configured."""
        mocker.patch.object(seed_module.sep_settings, "APPS", [_plugin("inventory")])

        await seed_module.init_sep_db()

        async with seed_maker() as session:
            states = await AppStateManager.all_lifecycle_states(session)
        assert "inventory" not in states

    async def test_idempotent_second_run(
        self, mocker, patched_seed, seed_maker
    ) -> None:
        """A second seed with the same configured set inserts no extra rows."""
        mocker.patch.object(
            seed_module.sep_settings, "APPS", [_plugin("snippets", enabled=True)]
        )

        await seed_module.init_sep_db()
        await seed_module.init_sep_db()

        async with seed_maker() as session:
            states = await AppStateManager.all_lifecycle_states(session)
        assert states == {"snippets": AppLifecycleEnum.ENABLED}

    async def test_existing_row_not_overwritten(
        self, mocker, patched_seed, seed_maker
    ) -> None:
        """An existing row keeps its value even when the YAML flips ``enabled``."""
        async with seed_maker() as session:
            session.add(
                AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLED)
            )
            await session.commit()

        mocker.patch.object(
            seed_module.sep_settings, "APPS", [_plugin("snippets", enabled=True)]
        )
        await seed_module.init_sep_db()

        async with seed_maker() as session:
            assert await AppStateManager.is_enabled(session, "snippets") is False

    async def test_orphan_rows_deleted(self, mocker, patched_seed, seed_maker) -> None:
        """Rows for apps no longer configured (incl. now-protected) are removed."""
        async with seed_maker() as session:
            session.add(
                AppState(app_key="ghost", lifecycle_state=AppLifecycleEnum.ENABLED)
            )
            session.add(
                AppState(app_key="inventory", lifecycle_state=AppLifecycleEnum.ENABLED)
            )
            await session.commit()

        mocker.patch.object(
            seed_module.sep_settings, "APPS", [_plugin("snippets", enabled=True)]
        )
        await seed_module.init_sep_db()

        async with seed_maker() as session:
            states = await AppStateManager.all_lifecycle_states(session)
        assert states == {"snippets": AppLifecycleEnum.ENABLED}

    async def test_child_app_not_seeded_and_stale_child_row_orphaned(
        self, mocker, patched_seed, seed_maker
    ) -> None:
        """Seed no row for a child app and orphan-delete a pre-existing child row."""
        async with seed_maker() as session:
            session.add(
                AppState(
                    app_key="mysql_backups/restore",
                    lifecycle_state=AppLifecycleEnum.ENABLED,
                )
            )
            await session.commit()

        mocker.patch.object(
            seed_module.sep_settings, "APPS", [_plugin("mysql_backups")]
        )
        await seed_module.init_sep_db()

        async with seed_maker() as session:
            states = await AppStateManager.all_lifecycle_states(session)
        assert states == {"mysql_backups": AppLifecycleEnum.ENABLED}

    async def test_periodic_task_seeding_still_runs(
        self, mocker, patched_seed, seed_maker
    ) -> None:
        """Periodic-task seeding still fires after AppState seeding (no regression)."""
        mocker.patch.object(seed_module.sep_settings, "APPS", [])

        await seed_module.init_sep_db()

        patched_seed.assert_awaited_once()


def test_reconciler_seeded_as_ungated_system_task() -> None:
    """The drain reconciler is seeded with no owner, so it is never gated off."""
    reconcilers = [
        task
        for schedule in seed_module.get_system_periodic_tasks()
        for task in schedule.tasks
        if task.task_name == "app.sep.app_drain.reconcile_disabling_apps"
    ]
    assert len(reconcilers) == 1
    assert reconcilers[0].owner_app_key is None


def _snippets_schedule(
    tasks: list[SystemPeriodicTaskSchedule],
) -> SystemPeriodicTaskSchedule:
    """Return the schedule carrying the ``sep__sync_snippets`` task."""
    return next(
        schedule
        for schedule in tasks
        if any(task.name == SNIPPETS_TASK for task in schedule.tasks)
    )


def test_builder_reads_sync_interval_at_call_time() -> None:
    """``get_system_periodic_tasks`` reflects the live ``SYNC_INTERVAL`` override.

    Built per call, so a DB-backed override published to the proxy snapshot is
    honored without a restart.
    """
    from app.core.celery.models import IntervalSchedule as CoreIntervalSchedule
    from app.sep.snippets.config import snippets_settings

    snippets_settings._set_snapshot(
        {"SYNC_INTERVAL": CoreIntervalSchedule(every=30, period=Period.MINUTES)}
    )
    try:
        schedule = _snippets_schedule(seed_module.get_system_periodic_tasks())
        assert schedule.schedule == CoreIntervalSchedule(
            every=30, period=Period.MINUTES
        )
    finally:
        snippets_settings._set_snapshot({})

    # A different override on the next call is reflected (no import-time freeze).
    snippets_settings._set_snapshot(
        {"SYNC_INTERVAL": CoreIntervalSchedule(every=5, period=Period.MINUTES)}
    )
    try:
        schedule = _snippets_schedule(seed_module.get_system_periodic_tasks())
        assert schedule.schedule == CoreIntervalSchedule(every=5, period=Period.MINUTES)
    finally:
        snippets_settings._set_snapshot({})


def test_celery_result_expires_configured() -> None:
    """Celery results have a TTL so result backends do not grow forever."""
    assert settings.CELERY.result_expires == CELERY_RESULT_EXPIRES_SECONDS


@pytest_asyncio.fixture(name="beat_maker")
async def beat_maker_fixture() -> AsyncIterator:
    """Provide a session maker bound to an in-memory celery-beat DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"celery_schema": None})
    async with engine.begin() as conn:
        await conn.run_sync(PeriodicTask.__table__.metadata.create_all)
    yield get_async_session_maker_from_engine(engine)


@pytest.mark.asyncio
class TestInitSepDbPeriodicTaskGating:
    """Tests for the periodic-task gating wired into ``init_sep_db``."""

    @pytest.mark.parametrize("app_enabled", [True, False])
    async def test_gate_reflects_app_state(
        self, mocker, seed_maker, beat_maker, app_enabled
    ) -> None:
        """``init_sep_db`` seeds wrapper rows and writes ``effective_enabled`` through."""
        async with beat_maker() as session:
            schedule = IntervalSchedule(every=10, period=Period.MINUTES)
            session.add(schedule)
            await session.flush()
            session.add(
                PeriodicTask(
                    name=SNIPPETS_TASK,
                    task="app.sep.celery.sync_snippets",
                    enabled=True,
                    schedule_model=schedule,
                )
            )
            await session.commit()

        mocker.patch.object(
            seed_module, "get_async_session_maker", return_value=seed_maker
        )
        mocker.patch.object(
            seed_module, "init_periodic_tasks_db", new_callable=mocker.AsyncMock
        )
        mocker.patch.object(
            periodic_tasks_module, "get_sep_session_maker", return_value=seed_maker
        )
        mocker.patch.object(
            periodic_tasks_module,
            "get_celery_beat_session_maker",
            return_value=beat_maker,
        )
        mocker.patch.object(
            seed_module,
            "get_system_periodic_tasks",
            return_value=[
                SystemPeriodicTaskSchedule(
                    schedule=IntervalSchedule(every=10, period=Period.MINUTES),
                    tasks=[
                        SystemPeriodicTaskData(
                            name=SNIPPETS_TASK,
                            task_name="app.sep.celery.sync_snippets",
                            owner_app_key="snippets",
                        ),
                    ],
                ),
            ],
        )
        mocker.patch.object(
            seed_module.sep_settings,
            "APPS",
            [_plugin("snippets", enabled=app_enabled)],
        )

        await seed_module.init_sep_db()

        async with seed_maker() as session:
            rows = await SEPPluginPeriodicTaskManager.list(session)
        assert {r.periodic_task_name for r in rows} == {SNIPPETS_TASK}

        async with beat_maker() as session:
            task = await BasePeriodicTaskManager.first(session, name=SNIPPETS_TASK)
        assert task.enabled is app_enabled
