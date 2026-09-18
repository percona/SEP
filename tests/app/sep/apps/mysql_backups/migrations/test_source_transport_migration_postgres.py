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

"""Test the ``source_transport`` migration against real PostgreSQL.

SQLite's sibling covers the happy-path upgrade/downgrade and the CHECK on the
default engine. PostgreSQL is where ``batch_alter_table`` emits a plain ALTER
instead of rebuilding the table, and where a misnamed CHECK would silently pass
SQLite's more permissive reflection — so the CHECK accept/reject cases run here
too.

Everything runs over ``asyncpg``: the sep track's ``env.py`` builds its own
async engine, and the ``test_postgres`` CI job installs the ``postgresql`` group
only, so no sync driver is available to lean on. Passing ``str(url)`` into a
sync ``create_engine`` is also unsafe — SQLAlchemy hides the password as
``***`` in the string form.
"""

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.utils.fields import AsyncDatabaseEngine
from app.sep.config import sep_settings
from tests.app.alembic_paths import ALEMBIC_INI
from tests.app.conftest import POSTGRES_DSN_ENV

_TRANSPORT_REVISION = "c8d9e0f1a2b3"
_PRE_TRANSPORT_REVISION = "b7c8d9e0f1a2"
_TABLE = "mysql_backup_run"
_COLUMN = "source_transport"
_CHECK_NAME = "cataloguedsourcetransport"

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres_async_url():
    """Return an ``asyncpg`` URL to the real-PostgreSQL test database.

    Skip when ``$SEP_TEST_POSTGRES_DSN`` is unset (local runs without
    PostgreSQL); the dedicated ``test_postgres`` CI job supplies it.
    """
    dsn = os.environ.get(POSTGRES_DSN_ENV)
    if not dsn:
        pytest.skip(f"{POSTGRES_DSN_ENV} not set; skipping real-PostgreSQL tests")
    return make_url(dsn).set(drivername="postgresql+asyncpg")


@pytest.fixture
def sep_postgres_alembic_config(postgres_async_url, monkeypatch: pytest.MonkeyPatch):
    """Point the sep track at real PostgreSQL and yield its Alembic config.

    ``command.upgrade`` builds its own engine inside the track's ``env.py`` from
    ``sep_settings.DATABASE`` rather than accepting one, so the settings are
    what must be redirected. Drop the schema on teardown so sibling tests
    inherit a clean database.
    """
    database = sep_settings.DATABASE
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

    cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    try:
        yield cfg, postgres_async_url
    finally:
        _await(postgres_async_url, _drop_schema)


def _await(url, coroutine_factory):
    """Run ``coroutine_factory`` against a fresh async engine and dispose of it."""

    async def _run():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                return await coroutine_factory(conn)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


async def _drop_schema(conn):
    """Drop and recreate the ``public`` schema."""
    await conn.execute(text("DROP SCHEMA public CASCADE"))
    await conn.execute(text("CREATE SCHEMA public"))


async def _run_state(conn) -> tuple[set[str], set[str]]:
    """Return column names and check-constraint names on ``mysql_backup_run``."""

    def _inspect(sync_conn) -> tuple[set[str], set[str]]:
        inspector = inspect(sync_conn)
        if _TABLE not in inspector.get_table_names():
            return set(), set()
        return (
            {column["name"] for column in inspector.get_columns(_TABLE)},
            {
                constraint["name"]
                for constraint in inspector.get_check_constraints(_TABLE)
            },
        )

    return await conn.run_sync(_inspect)


async def _insert_run(conn, *, source_transport: str | None, history_id: int) -> None:
    """Insert a minimal catalog row, optionally with ``source_transport``."""
    await conn.execute(
        text(
            f"INSERT INTO {_TABLE} "
            "(task_history_id, backup_type, source_transport, created_at) "
            "VALUES (:history_id, 'MYDUMPER', :source_transport, "
            "'2026-09-18 12:00:00+00')"
        ),
        {"history_id": history_id, "source_transport": source_transport},
    )


def test_upgrade_adds_column_and_check(sep_postgres_alembic_config) -> None:
    """Assert upgrade stamps the column and CHECK on native PostgreSQL ALTER."""
    cfg, url = sep_postgres_alembic_config
    command.upgrade(cfg, _TRANSPORT_REVISION)

    columns, checks = _await(url, _run_state)

    assert _COLUMN in columns
    assert _CHECK_NAME in checks


def test_upgrade_check_accepts_member_names(sep_postgres_alembic_config) -> None:
    """Assert the CHECK allows ``S3`` / ``GCS`` / NULL on PostgreSQL."""
    cfg, url = sep_postgres_alembic_config
    command.upgrade(cfg, _TRANSPORT_REVISION)

    async def _seed(conn):
        await _insert_run(conn, source_transport="S3", history_id=1)
        await _insert_run(conn, source_transport="GCS", history_id=2)
        await _insert_run(conn, source_transport=None, history_id=3)

    _await(url, _seed)


def test_upgrade_check_rejects_unknown_transport(sep_postgres_alembic_config) -> None:
    """Assert PostgreSQL rejects a value outside the CHECK."""
    cfg, url = sep_postgres_alembic_config
    command.upgrade(cfg, _TRANSPORT_REVISION)

    with pytest.raises(IntegrityError):
        _await(
            url, lambda conn: _insert_run(conn, source_transport="SSH", history_id=1)
        )


def test_downgrade_drops_column_and_check(sep_postgres_alembic_config) -> None:
    """Assert downgrade removes the column and CHECK via plain ALTER."""
    cfg, url = sep_postgres_alembic_config
    command.upgrade(cfg, _TRANSPORT_REVISION)
    command.downgrade(cfg, _PRE_TRANSPORT_REVISION)

    columns, checks = _await(url, _run_state)

    assert _COLUMN not in columns
    assert _CHECK_NAME not in checks
