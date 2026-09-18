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
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

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
def sep_postgres_alembic_config(monkeypatch: pytest.MonkeyPatch):
    """Point the sep track at real PostgreSQL and yield its Alembic config.

    Skip when ``$SEP_TEST_POSTGRES_DSN`` is unset. Drop the public schema on
    teardown so sibling postgres tests inherit a clean database.
    """
    dsn = os.environ.get(POSTGRES_DSN_ENV)
    if not dsn:
        pytest.skip(f"{POSTGRES_DSN_ENV} not set; skipping real-PostgreSQL tests")
    sync_url = make_url(dsn).set(drivername="postgresql+psycopg2")

    database = sep_settings.DATABASE
    monkeypatch.setattr(database, "ENGINE", AsyncDatabaseEngine.POSTGRESQL)
    monkeypatch.setattr(database, "USER", sync_url.username)
    monkeypatch.setattr(
        database,
        "PASSWORD",
        SecretStr(sync_url.password) if sync_url.password else None,
    )
    monkeypatch.setattr(database, "HOST", sync_url.host)
    monkeypatch.setattr(database, "PORT", sync_url.port)
    monkeypatch.setattr(database, "NAME", sync_url.database)

    cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    try:
        yield cfg, str(sync_url)
    finally:
        engine = create_engine(sync_url)
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql("DROP SCHEMA public CASCADE")
                conn.exec_driver_sql("CREATE SCHEMA public")
        finally:
            engine.dispose()


def _run_state(sync_url: str) -> tuple[set[str], set[str]]:
    """Return column names and check-constraint names on ``mysql_backup_run``."""
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        if _TABLE not in inspector.get_table_names():
            return set(), set()
        return (
            {column["name"] for column in inspector.get_columns(_TABLE)},
            {
                constraint["name"]
                for constraint in inspector.get_check_constraints(_TABLE)
            },
        )
    finally:
        engine.dispose()


def _insert_run(sync_url: str, *, source_transport: str | None, history_id: int) -> None:
    """Insert a minimal catalog row, optionally with ``source_transport``."""
    engine = create_engine(sync_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO {_TABLE} "
                    "(task_history_id, backup_type, source_transport, created_at) "
                    "VALUES (:history_id, 'MYDUMPER', :source_transport, "
                    "'2026-09-18 12:00:00+00')"
                ),
                {"history_id": history_id, "source_transport": source_transport},
            )
    finally:
        engine.dispose()


def test_upgrade_adds_column_and_check(sep_postgres_alembic_config) -> None:
    """Assert upgrade stamps the column and CHECK on native PostgreSQL ALTER."""
    cfg, sync_url = sep_postgres_alembic_config
    command.upgrade(cfg, _TRANSPORT_REVISION)

    columns, checks = _run_state(sync_url)

    assert _COLUMN in columns
    assert _CHECK_NAME in checks


def test_upgrade_check_accepts_member_names(sep_postgres_alembic_config) -> None:
    """Assert the CHECK allows ``S3`` / ``GCS`` / NULL on PostgreSQL."""
    cfg, sync_url = sep_postgres_alembic_config
    command.upgrade(cfg, _TRANSPORT_REVISION)

    _insert_run(sync_url, source_transport="S3", history_id=1)
    _insert_run(sync_url, source_transport="GCS", history_id=2)
    _insert_run(sync_url, source_transport=None, history_id=3)


def test_upgrade_check_rejects_unknown_transport(sep_postgres_alembic_config) -> None:
    """Assert PostgreSQL rejects a value outside the CHECK."""
    cfg, sync_url = sep_postgres_alembic_config
    command.upgrade(cfg, _TRANSPORT_REVISION)

    with pytest.raises(IntegrityError):
        _insert_run(sync_url, source_transport="SSH", history_id=1)


def test_downgrade_drops_column_and_check(sep_postgres_alembic_config) -> None:
    """Assert downgrade removes the column and CHECK via plain ALTER."""
    cfg, sync_url = sep_postgres_alembic_config
    command.upgrade(cfg, _TRANSPORT_REVISION)
    command.downgrade(cfg, _PRE_TRANSPORT_REVISION)

    columns, checks = _run_state(sync_url)

    assert _COLUMN not in columns
    assert _CHECK_NAME not in checks
