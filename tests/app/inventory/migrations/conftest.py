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

"""Shared fixtures for the Inventory-track migration tests."""

import asyncio
import os
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import Any, TypeVar

import pytest
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url, URL
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.utils.fields import AsyncDatabaseEngine
from app.inventory.config import inventory_settings
from tests.app.alembic_paths import ALEMBIC_INI
from tests.app.conftest import POSTGRES_DSN_ENV

_T = TypeVar("_T")

#: The ``created_at`` / ``updated_at`` pair every real-PostgreSQL seed needs,
#: spelled with the offset ``timestamptz`` requires.
SEED_TIMESTAMPS = "'2026-01-01 00:00:00+00', '2026-01-01 00:00:00+00'"

#: The head immediately before the at-least-one-fact CHECK lands. The SQLite and
#: real-PostgreSQL halves of that revision's coverage must upgrade from the same
#: point for their seeded rows to mean the same thing.
HOST_OBSERVATION_PRE_CONSTRAINT_REVISION = "b351dd0aaed8"


@pytest.fixture
def inventory_alembic_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Config, str]:
    """Return an Alembic ``Config`` and sync URL pointing at a temp SQLite file.

    ``PRAGMA foreign_keys`` is deliberately left off: batch mode recreates
    ``node``, which ``service.node_id`` references, and FK enforcement during
    that rebuild is what makes batch migrations fail on SQLite.
    """
    db_path = tmp_path / "test_inventory.sqlite"
    sync_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(inventory_settings.DATABASE, "HOST", "")
    monkeypatch.setattr(inventory_settings.DATABASE, "NAME", str(db_path))

    cfg = Config(str(ALEMBIC_INI), ini_section="inventory")
    return cfg, sync_url


@pytest.fixture
def postgres_async_url() -> URL:
    """Return an ``asyncpg`` URL to the real-PostgreSQL test database.

    Skip when ``$EXTENSIONS_TEST_POSTGRES_DSN`` is unset (local runs without
    PostgreSQL); the dedicated ``test_postgres`` CI job supplies it.
    """
    dsn = os.environ.get(POSTGRES_DSN_ENV)
    if not dsn:
        pytest.skip(f"{POSTGRES_DSN_ENV} not set; skipping real-PostgreSQL tests")
    return make_url(dsn).set(drivername="postgresql+asyncpg")


@pytest.fixture
def inventory_postgres_config(
    postgres_async_url: URL, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Config, URL]]:
    """Point the inventory track at real PostgreSQL and yield its Alembic config.

    ``command.upgrade`` builds its own engine inside the track's ``env.py`` from
    ``inventory_settings.DATABASE`` rather than accepting one, so the settings
    are what must be redirected. Drop the schema on teardown so sibling tests
    inherit a clean database.
    """
    database = inventory_settings.DATABASE
    monkeypatch.setattr(database, "ENGINE", AsyncDatabaseEngine.POSTGRESQL)
    monkeypatch.setattr(database, "USER", postgres_async_url.username)
    monkeypatch.setattr(
        database,
        "PASSWORD",
        SecretStr(postgres_async_url.password) if postgres_async_url.password else None,
    )
    monkeypatch.setattr(database, "HOST", postgres_async_url.host)
    monkeypatch.setattr(database, "PORT", postgres_async_url.port)
    monkeypatch.setattr(database, "NAME", postgres_async_url.database)

    cfg = Config(str(ALEMBIC_INI), ini_section="inventory")
    try:
        yield cfg, postgres_async_url
    finally:
        run_on_postgres(postgres_async_url, _drop_schema)


def run_on_postgres(
    url: URL,
    coroutine_factory: Callable[[AsyncConnection], Coroutine[Any, Any, _T]],
) -> _T:
    """Run ``coroutine_factory`` against a fresh async engine and dispose of it.

    Each call opens its own engine and transaction, so a case that expects an
    ``IntegrityError`` leaves nothing poisoned behind for the next one.

    :param url: The ``asyncpg`` URL to connect through.
    :param coroutine_factory: A callable taking the open connection.
    :return: Whatever ``coroutine_factory`` returned.
    """

    async def _run() -> _T:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                return await coroutine_factory(conn)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


async def _drop_schema(conn: AsyncConnection) -> None:
    """Drop and recreate the ``public`` schema."""
    await conn.execute(text("DROP SCHEMA public CASCADE"))
    await conn.execute(text("CREATE SCHEMA public"))
