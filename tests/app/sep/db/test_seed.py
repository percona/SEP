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
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.sep.crud import AppStateManager
from app.sep.db import seed as seed_module
from app.sep.models import AppState


def _plugin(key: str, *, enabled: bool = True) -> MagicMock:
    """Build a minimal Plugin stand-in carrying ``module_name`` and ``enabled``."""
    plugin = MagicMock()
    plugin.module_name = f"app.sep.plugins.{key}"
    plugin.enabled = enabled
    return plugin


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
    """Patch the seed module's session maker and stub the periodic-task seeding."""
    mocker.patch.object(seed_module, "get_async_session_maker", return_value=seed_maker)
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
            "PLUGINS",
            [
                _plugin("snippets", enabled=True),
                _plugin("checksums", enabled=False),
                _plugin("inventory", enabled=True),
            ],
        )

        await seed_module.init_sep_db()

        async with seed_maker() as session:
            states = await AppStateManager.all_states(session)
        assert states == {"snippets": True, "checksums": False}

    async def test_inventory_is_never_seeded(
        self, mocker, patched_seed, seed_maker
    ) -> None:
        """The protected ``inventory`` app gets no row even when configured."""
        mocker.patch.object(seed_module.sep_settings, "PLUGINS", [_plugin("inventory")])

        await seed_module.init_sep_db()

        async with seed_maker() as session:
            states = await AppStateManager.all_states(session)
        assert "inventory" not in states

    async def test_idempotent_second_run(
        self, mocker, patched_seed, seed_maker
    ) -> None:
        """A second seed with the same configured set inserts no extra rows."""
        mocker.patch.object(
            seed_module.sep_settings, "PLUGINS", [_plugin("snippets", enabled=True)]
        )

        await seed_module.init_sep_db()
        await seed_module.init_sep_db()

        async with seed_maker() as session:
            states = await AppStateManager.all_states(session)
        assert states == {"snippets": True}

    async def test_existing_row_not_overwritten(
        self, mocker, patched_seed, seed_maker
    ) -> None:
        """An existing row keeps its value even when the YAML flips ``enabled``."""
        async with seed_maker() as session:
            session.add(AppState(app_key="snippets", enabled=False))
            await session.commit()

        mocker.patch.object(
            seed_module.sep_settings, "PLUGINS", [_plugin("snippets", enabled=True)]
        )
        await seed_module.init_sep_db()

        async with seed_maker() as session:
            assert await AppStateManager.is_enabled(session, "snippets") is False

    async def test_orphan_rows_deleted(self, mocker, patched_seed, seed_maker) -> None:
        """Rows for apps no longer configured (incl. now-protected) are removed."""
        async with seed_maker() as session:
            session.add(AppState(app_key="ghost", enabled=True))
            session.add(AppState(app_key="inventory", enabled=True))
            await session.commit()

        mocker.patch.object(
            seed_module.sep_settings, "PLUGINS", [_plugin("snippets", enabled=True)]
        )
        await seed_module.init_sep_db()

        async with seed_maker() as session:
            states = await AppStateManager.all_states(session)
        assert states == {"snippets": True}

    async def test_periodic_task_seeding_still_runs(
        self, mocker, patched_seed, seed_maker
    ) -> None:
        """Periodic-task seeding still fires after AppState seeding (no regression)."""
        mocker.patch.object(seed_module.sep_settings, "PLUGINS", [])

        await seed_module.init_sep_db()

        patched_seed.assert_awaited_once()
