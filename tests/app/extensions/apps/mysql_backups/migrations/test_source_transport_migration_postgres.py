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

Schema isolation follows ``postgres_worker_schema()``: Alembic and the
verification connections share a per-xdist-worker ``search_path``, and teardown
drops only that schema — never ``public`` — so parallel workers and sibling
Postgres tests do not erase each other.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url, URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    async_engine_from_config as real_async_engine_from_config,
)
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    create_async_engine,
)

from app.core.utils.fields import AsyncDatabaseEngine
from app.extensions.config import extensions_settings
from tests.app.alembic_paths import ALEMBIC_INI
from tests.app.conftest import POSTGRES_DSN_ENV, postgres_worker_schema

_TRANSPORT_REVISION = "c8d9e0f1a2b3"
_PRE_TRANSPORT_REVISION = "b7c8d9e0f1a2"
_TABLE = "mysql_backup_run"
_COLUMN = "source_transport"
_CHECK_NAME = "cataloguedsourcetransport"

T = TypeVar("T")

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres_async_url():
    """Return an ``asyncpg`` URL to the real-PostgreSQL test database.

    Skip when ``$EXTENSIONS_TEST_POSTGRES_DSN`` is unset (local runs without
    PostgreSQL); the dedicated ``test_postgres`` CI job supplies it.
    """
    dsn = os.environ.get(POSTGRES_DSN_ENV)
    if not dsn:
        pytest.skip(f"{POSTGRES_DSN_ENV} not set; skipping real-PostgreSQL tests")
    return make_url(dsn).set(drivername="postgresql+asyncpg")


@pytest.fixture
def extensions_postgres_alembic_config(
    postgres_async_url: URL, monkeypatch: pytest.MonkeyPatch
):
    """Point the sep track at a per-worker PostgreSQL schema and yield Alembic config.

    ``command.upgrade`` builds its own engine inside the track's ``env.py`` from
    ``extensions_settings.DATABASE``, so settings are redirected and
    ``sqlalchemy.ext.asyncio.async_engine_from_config`` is patched before Alembic
    loads ``env.py`` (which cannot be imported outside a migration context) so the
    engine it builds sets ``search_path`` to :func:`postgres_worker_schema`.
    Teardown drops only that schema.
    """
    schema = postgres_worker_schema()
    database = extensions_settings.DATABASE
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

    def _engine_with_worker_search_path(*args, **kwargs):
        connect_args = dict(kwargs.pop("connect_args", None) or {})
        server_settings = dict(connect_args.get("server_settings") or {})
        server_settings["search_path"] = schema
        connect_args["server_settings"] = server_settings
        kwargs["connect_args"] = connect_args
        return real_async_engine_from_config(*args, **kwargs)

    # Patch the sqlalchemy symbol ``env.py`` imports; do not import
    # ``app.extensions.migrations.env`` here — ``context.config`` only exists inside
    # an Alembic run, and a top-level import breaks ``pytest -m 'not postgres'``
    # collection of this module.
    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.async_engine_from_config",
        _engine_with_worker_search_path,
    )

    cfg = Config(str(ALEMBIC_INI), ini_section="extensions")
    _manage_schema(postgres_async_url, schema, create=True)
    try:
        yield cfg, postgres_async_url, schema
    finally:
        _manage_schema(postgres_async_url, schema, create=False)


def _manage_schema(url: URL, schema: str, *, create: bool) -> None:
    """Create or drop ``schema`` on a connection that does not pin ``search_path``."""

    async def _run() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                if create:
                    await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
                else:
                    await conn.execute(
                        text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                    )
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _await(
    url: URL,
    schema: str,
    coroutine_factory: Callable[[AsyncConnection], Awaitable[T]],
) -> T:
    """Run ``coroutine_factory`` on a fresh engine pinned to ``schema``."""

    async def _run() -> T:
        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": schema}}
        )
        try:
            async with engine.begin() as conn:
                return await coroutine_factory(conn)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


async def _run_state(conn: AsyncConnection) -> tuple[set[str], set[str]]:
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


async def _insert_run(
    conn: AsyncConnection, *, source_transport: str | None, history_id: int
) -> None:
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


class TestSourceTransportMigration:
    """Define tests for the ``source_transport`` column and CHECK on PostgreSQL."""

    def test_upgrade_adds_column_and_check(
        self, extensions_postgres_alembic_config
    ) -> None:
        """Assert upgrade stamps the column and CHECK on native PostgreSQL ALTER."""
        cfg, url, schema = extensions_postgres_alembic_config
        command.upgrade(cfg, _TRANSPORT_REVISION)

        columns, checks = _await(url, schema, _run_state)

        assert _COLUMN in columns
        assert _CHECK_NAME in checks

    def test_upgrade_check_accepts_member_names(
        self, extensions_postgres_alembic_config
    ) -> None:
        """Assert the CHECK allows ``S3`` / ``GCS`` / NULL on PostgreSQL."""
        cfg, url, schema = extensions_postgres_alembic_config
        command.upgrade(cfg, _TRANSPORT_REVISION)

        async def _seed(conn: AsyncConnection) -> None:
            await _insert_run(conn, source_transport="S3", history_id=1)
            await _insert_run(conn, source_transport="GCS", history_id=2)
            await _insert_run(conn, source_transport=None, history_id=3)

        _await(url, schema, _seed)

    def test_upgrade_check_rejects_unknown_transport(
        self, extensions_postgres_alembic_config
    ) -> None:
        """Assert PostgreSQL rejects a value outside the CHECK."""
        cfg, url, schema = extensions_postgres_alembic_config
        command.upgrade(cfg, _TRANSPORT_REVISION)

        with pytest.raises(IntegrityError):
            _await(
                url,
                schema,
                lambda conn: _insert_run(conn, source_transport="SSH", history_id=1),
            )

    def test_downgrade_drops_column_and_check(
        self, extensions_postgres_alembic_config
    ) -> None:
        """Assert downgrade removes the column and CHECK via plain ALTER."""
        cfg, url, schema = extensions_postgres_alembic_config
        command.upgrade(cfg, _TRANSPORT_REVISION)
        command.downgrade(cfg, _PRE_TRANSPORT_REVISION)

        columns, checks = _await(url, schema, _run_state)

        assert _COLUMN not in columns
        assert _CHECK_NAME not in checks
