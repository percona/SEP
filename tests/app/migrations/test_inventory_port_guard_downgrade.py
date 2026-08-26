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

"""Test the port-guard revision's downgrade against a real PostgreSQL database.

Narrowing ``ix_service_port_node_id`` lets two identified services share one
node and port, so the downgrade has to delete the rows the restored index could
not hold before it recreates that index. Neither half is checkable on the
default test lane: SQLite is not the deployment engine, and ``alembic check``
verifies only that a migration exists, never that its ``downgrade()`` runs
against the data its ``upgrade()`` admits.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.core.utils.fields import AsyncDatabaseEngine
from app.inventory.config import inventory_settings

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
POSTGRES_DSN_ENV = "SEP_TEST_POSTGRES_DSN"

#: The revision immediately below the port-guard one — downgrading to it runs
#: the deletion and restores the pre-narrowing index.
_PRE_PORT_GUARD_REVISION = "c7d1e94ab3f2"

_SEED = """
INSERT INTO node (address, name, type, retirement_key, created_at, updated_at)
VALUES ('10.0.0.1', 'n1', 'generic', -1, NOW(), NOW());
INSERT INTO service
    (name, type, port, node_id, external_id, retirement_key, port_guard_key,
     created_at, updated_at)
SELECT 'svc-a', 'postgresql', 5432, id, 'ext-a', -1, NULL, NOW(), NOW() FROM node;
INSERT INTO service
    (name, type, port, node_id, external_id, retirement_key, port_guard_key,
     created_at, updated_at)
SELECT 'svc-b', 'postgresql', 5432, id, 'ext-b', -1, NULL, NOW(), NOW() FROM node;
INSERT INTO service
    (name, type, port, node_id, external_id, retirement_key, port_guard_key,
     created_at, updated_at)
SELECT 'svc-noport-a', 'postgresql', NULL, id, 'ext-c', -1, NULL, NOW(), NOW()
FROM node;
INSERT INTO service
    (name, type, port, node_id, external_id, retirement_key, port_guard_key,
     created_at, updated_at)
SELECT 'svc-noport-b', 'postgresql', NULL, id, 'ext-d', -1, NULL, NOW(), NOW()
FROM node;
"""


@pytest.fixture
def postgres_sync_url():
    """Return the psycopg2 URL for the configured test PostgreSQL, or skip."""
    dsn = os.environ.get(POSTGRES_DSN_ENV)
    if not dsn:
        pytest.skip(f"{POSTGRES_DSN_ENV} not set; skipping real-PostgreSQL tests")
    return make_url(dsn).set(drivername="postgresql+psycopg2")


@pytest.fixture
def inventory_postgres_db(postgres_sync_url, monkeypatch):
    """Point the inventory Alembic track at the real test PostgreSQL database.

    ``command.upgrade`` builds its own engine from ``inventory_settings.DATABASE
    .URL`` via the track's ``env.py``, so redirecting the settings is what moves
    the migration off the default SQLite file. Drop the schema on teardown so the
    tables this creates do not leak into sibling tests.
    """
    monkeypatch.setattr(
        inventory_settings.DATABASE, "ENGINE", AsyncDatabaseEngine.POSTGRESQL
    )
    monkeypatch.setattr(inventory_settings.DATABASE, "USER", postgres_sync_url.username)
    monkeypatch.setattr(
        inventory_settings.DATABASE,
        "PASSWORD",
        SecretStr(postgres_sync_url.password) if postgres_sync_url.password else None,
    )
    monkeypatch.setattr(inventory_settings.DATABASE, "HOST", postgres_sync_url.host)
    monkeypatch.setattr(inventory_settings.DATABASE, "PORT", postgres_sync_url.port)
    monkeypatch.setattr(inventory_settings.DATABASE, "NAME", postgres_sync_url.database)
    try:
        yield postgres_sync_url
    finally:
        engine = create_engine(postgres_sync_url)
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql("DROP SCHEMA public CASCADE")
                conn.exec_driver_sql("CREATE SCHEMA public")
        finally:
            engine.dispose()


def _service_names(sync_url) -> set[str]:
    """Return the names of every surviving service row."""
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            return {row[0] for row in conn.exec_driver_sql("SELECT name FROM service")}
    finally:
        engine.dispose()


@pytest.mark.xdist_group("shared_postgres_db")
@pytest.mark.postgres
def test_downgrade_drops_the_extra_same_port_service(inventory_postgres_db):
    """Delete the extra same-port service, keeping the lowest-id row of the group.

    The port-less rows are the control: SQL ``GROUP BY`` treats their NULL ports
    as equal, so a deletion without the ``port IS NOT NULL`` filter would collapse
    them into one group and drop all but the first — rows the restored index never
    constrained.
    """
    config = Config(str(ALEMBIC_INI), ini_section="inventory")
    command.upgrade(config, "heads")
    engine = create_engine(inventory_postgres_db)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(_SEED)
    finally:
        engine.dispose()

    command.downgrade(config, _PRE_PORT_GUARD_REVISION)

    assert _service_names(inventory_postgres_db) == {
        "svc-a",
        "svc-noport-a",
        "svc-noport-b",
    }


@pytest.mark.xdist_group("shared_postgres_db")
@pytest.mark.postgres
def test_port_guard_revision_round_trips(inventory_postgres_db):
    """Re-apply the revision after a downgrade that had rows to remediate."""
    config = Config(str(ALEMBIC_INI), ini_section="inventory")
    command.upgrade(config, "heads")
    engine = create_engine(inventory_postgres_db)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(_SEED)
    finally:
        engine.dispose()
    command.downgrade(config, _PRE_PORT_GUARD_REVISION)

    command.upgrade(config, "heads")

    assert _service_names(inventory_postgres_db) == {
        "svc-a",
        "svc-noport-a",
        "svc-noport-b",
    }
