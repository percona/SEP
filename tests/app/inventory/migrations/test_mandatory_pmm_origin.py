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

"""Test the Inventory-track mandatory-PMM-origin migration on SQLite.

SQLite cannot prove the whole revision: it stores the ``source`` enum as free
text, so an invalid label passes here and only PostgreSQL rejects it, and
``batch_alter_table`` recreates the table here while emitting a plain ``ALTER``
there. The real-PostgreSQL half lives in
``test_mandatory_pmm_origin_postgres.py``; what these cases pin is the
classification, backfill and cascade logic, which is dialect-neutral.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.inventory.config import inventory_settings

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# The head immediately before the PMM origin becomes mandatory.
_PRE_ORIGIN_REVISION = "c7d1e94ab3f2"

_LEGACY_PREFIX = "sep-legacy:"

_INSERT_NODE = (
    "INSERT INTO node "
    "(created_at, updated_at, address, name, external_id, source, type, "
    "retired_at, retirement_key) "
    "VALUES ('2026-01-01 00:00:00', '2026-01-01 00:00:00', ?, ?, ?, ?, "
    "'generic', ?, ?)"
)
_INSERT_SERVICE = (
    "INSERT INTO service "
    "(created_at, updated_at, external_id, name, type, port, node_id, "
    "retired_at, retirement_key) "
    "VALUES ('2026-01-01 00:00:00', '2026-01-01 00:00:00', ?, ?, 'MYSQL', ?, ?, "
    "NULL, -1)"
)
_INSERT_SCHEMA = (
    "INSERT INTO schema "
    "(created_at, updated_at, name, service_id, retired_at, retirement_key) "
    "VALUES ('2026-01-01 00:00:00', '2026-01-01 00:00:00', ?, ?, NULL, -1)"
)
_INSERT_TABLE = (
    'INSERT INTO "table" '
    '(created_at, updated_at, name, "create", keys, schema_id, retired_at, '
    "retirement_key) "
    "VALUES ('2026-01-01 00:00:00', '2026-01-01 00:00:00', ?, "
    "'CREATE TABLE t (id INT)', '{}', ?, NULL, -1)"
)

_MANDATORY_COLUMNS = (
    ("node", "external_id"),
    ("node", "source"),
    ("service", "external_id"),
)

#: Columns no revision at or below ``_PRE_ORIGIN_REVISION`` declares, added by a
#: later one and therefore dropped again on the way down to it.
_COLUMNS_ABOVE_PRE_ORIGIN = frozenset(
    {
        "last_synced_at",
        "last_sync_error",
        "sync_failing_since",
        "consecutive_failures",
    }
)


@pytest.fixture
def inventory_alembic_config(tmp_path, monkeypatch):
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


def _seed_node(
    conn, address, name, external_id, source, retired_at=None, retirement_key=-1
):
    """Insert a ``node`` row and return its primary key."""
    conn.exec_driver_sql(
        _INSERT_NODE, (address, name, external_id, source, retired_at, retirement_key)
    )
    return conn.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()


def _seed_service(conn, external_id, name, port, node_id):
    """Insert a ``service`` row and return its primary key."""
    conn.exec_driver_sql(_INSERT_SERVICE, (external_id, name, port, node_id))
    return conn.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()


def _seed_schema(conn, name, service_id):
    """Insert a ``schema`` row and return its primary key."""
    conn.exec_driver_sql(_INSERT_SCHEMA, (name, service_id))
    return conn.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()


def _seed_table(conn, name, schema_id):
    """Insert a ``table`` row and return its primary key."""
    conn.exec_driver_sql(_INSERT_TABLE, (name, schema_id))
    return conn.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()


def _row(conn, table_name, entity_id):
    """Return the named table's row for ``entity_id`` as a mapping."""
    quoted = f'"{table_name}"' if table_name == "table" else table_name
    result = conn.exec_driver_sql(
        f"SELECT * FROM {quoted} WHERE id = ?",
        (entity_id,),
    ).one()
    return result._mapping


def _row_at_pre_origin(conn, table_name, entity_id):
    """Return the row restricted to the columns the pre-origin schema declares.

    A revision above ``_PRE_ORIGIN_REVISION`` may add columns, and downgrading
    to it drops them on the way past. Comparing whole rows across that boundary
    would then fail on the schema difference rather than on the data this test
    is about, so the later columns are excluded from the captured expectation.

    :param conn: The open connection to read through.
    :param table_name: The table holding the row.
    :param entity_id: The row's primary key.
    :return: The row's pre-origin columns and their values.
    """
    return {
        name: value
        for name, value in _row(conn, table_name, entity_id).items()
        if name not in _COLUMNS_ABOVE_PRE_ORIGIN
    }


def test_origin_less_node_is_retired_not_deleted(inventory_alembic_config):
    """Retire an origin-less node on its own primary key instead of deleting it."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, _PRE_ORIGIN_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node_id = _seed_node(conn, "10.0.0.1", "legacy", None, None)
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node = _row(conn, "node", node_id)
            assert node["retired_at"] is not None
            assert node["retirement_key"] == node_id
    finally:
        engine.dispose()


def test_origin_less_node_gets_a_synthetic_origin(inventory_alembic_config):
    """Stamp the PMM source and a prefixed identifier onto an origin-less node."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, _PRE_ORIGIN_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node_id = _seed_node(conn, "10.0.0.1", "legacy", None, None)
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node = _row(conn, "node", node_id)
            assert node["source"] == "PMM"
            assert node["external_id"] == f"{_LEGACY_PREFIX}{node_id}"
    finally:
        engine.dispose()


def test_partial_origin_keeps_its_real_external_id(inventory_alembic_config):
    """Preserve a real external_id while stamping only the missing source."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, _PRE_ORIGIN_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node_id = _seed_node(conn, "10.0.0.2", "half", "/node_id/real", None)
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node = _row(conn, "node", node_id)
            assert node["external_id"] == "/node_id/real"
            assert node["source"] == "PMM"
            assert node["retired_at"] is not None
    finally:
        engine.dispose()


def test_retirement_cascades_through_the_subtree(inventory_alembic_config):
    """Retire the service, schema and table hanging off an origin-less node."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, _PRE_ORIGIN_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node_id = _seed_node(conn, "10.0.0.3", "deep", None, None)
            service_id = _seed_service(conn, "/service_id/deep", "svc", 3306, node_id)
            schema_id = _seed_schema(conn, "sch", service_id)
            table_id = _seed_table(conn, "tbl", schema_id)
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            for table_name, entity_id in (
                ("node", node_id),
                ("service", service_id),
                ("schema", schema_id),
                ("table", table_id),
            ):
                row = _row(conn, table_name, entity_id)
                assert row["retired_at"] is not None, table_name
                assert row["retirement_key"] == entity_id, table_name
    finally:
        engine.dispose()


def test_two_origin_less_nodes_get_distinct_identifiers(inventory_alembic_config):
    """Stamp two origin-less nodes in one pass without colliding on the index."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, _PRE_ORIGIN_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            first = _seed_node(conn, "10.0.0.4", "one", None, None)
            second = _seed_node(conn, "10.0.0.5", "two", None, None)
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            assert (
                _row(conn, "node", first)["external_id"]
                != _row(conn, "node", second)["external_id"]
            )
    finally:
        engine.dispose()


def test_origin_less_service_under_a_healthy_node(inventory_alembic_config):
    """Retire and stamp the service while leaving its PMM-sourced node active."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, _PRE_ORIGIN_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node_id = _seed_node(conn, "10.0.0.6", "healthy", "/node_id/ok", "PMM")
            service_id = _seed_service(conn, None, "orphan-svc", 3307, node_id)
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            service = _row(conn, "service", service_id)
            assert service["retired_at"] is not None
            assert service["external_id"] == f"{_LEGACY_PREFIX}{service_id}"

            node = _row(conn, "node", node_id)
            assert node["retired_at"] is None
            assert node["external_id"] == "/node_id/ok"
    finally:
        engine.dispose()


def test_pmm_sourced_rows_pass_through_untouched(inventory_alembic_config):
    """Leave a node and service that already carry an origin exactly as they were."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, _PRE_ORIGIN_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node_id = _seed_node(conn, "10.0.0.7", "good", "/node_id/good", "PMM")
            service_id = _seed_service(conn, "/service_id/good", "svc", 3308, node_id)
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node = _row(conn, "node", node_id)
            assert node["retired_at"] is None
            assert node["external_id"] == "/node_id/good"
            assert node["source"] == "PMM"

            service = _row(conn, "service", service_id)
            assert service["retired_at"] is None
            assert service["external_id"] == "/service_id/good"
    finally:
        engine.dispose()


def test_already_retired_row_keeps_its_original_timestamp(inventory_alembic_config):
    """Stamp an origin onto an existing tombstone without rewriting retired_at."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, _PRE_ORIGIN_REVISION)

    original = "2025-06-01 12:00:00"
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node_id = _seed_node(
                conn, "10.0.0.8", "tombstone", None, None, retired_at=original
            )
            conn.exec_driver_sql(
                "UPDATE node SET retirement_key = id WHERE id = ?", (node_id,)
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node = _row(conn, "node", node_id)
            assert str(node["retired_at"]).startswith("2025-06-01")
            assert node["source"] == "PMM"
            assert node["external_id"] == f"{_LEGACY_PREFIX}{node_id}"
    finally:
        engine.dispose()


def test_columns_become_not_nullable(inventory_alembic_config):
    """Report all three constrained columns as NOT NULL after the upgrade."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        for table_name, column in _MANDATORY_COLUMNS:
            columns = {c["name"]: c for c in inspector.get_columns(table_name)}
            assert columns[column]["nullable"] is False, f"{table_name}.{column}"
    finally:
        engine.dispose()


def test_greenfield_database_upgrades(inventory_alembic_config):
    """Apply the revision to an empty database without error."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM node").scalar_one() == 0
    finally:
        engine.dispose()


def test_downgrade_restores_nullability_and_leaves_data_alone(
    inventory_alembic_config,
):
    """Restore the three columns to nullable without touching a single row."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, _PRE_ORIGIN_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node_id = _seed_node(conn, "10.0.0.9", "legacy", None, None)
            service_id = _seed_service(conn, None, "svc", 3309, node_id)
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            stamped_node = _row_at_pre_origin(conn, "node", node_id)
            stamped_service = _row_at_pre_origin(conn, "service", service_id)
    finally:
        engine.dispose()

    command.downgrade(cfg, _PRE_ORIGIN_REVISION)

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        for table_name, column in _MANDATORY_COLUMNS:
            columns = {c["name"]: c for c in inspector.get_columns(table_name)}
            assert columns[column]["nullable"] is True, f"{table_name}.{column}"

        with engine.begin() as conn:
            assert dict(_row(conn, "node", node_id)) == stamped_node
            assert dict(_row(conn, "service", service_id)) == stamped_service
    finally:
        engine.dispose()


def test_reupgrade_after_downgrade_is_a_no_op_over_stamped_rows(
    inventory_alembic_config,
):
    """Leave every stamped row untouched on a second upgrade, no NULLs remaining."""
    cfg, sync_url = inventory_alembic_config
    command.upgrade(cfg, _PRE_ORIGIN_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            node_id = _seed_node(conn, "10.0.0.10", "legacy", None, None)
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            stamped = dict(_row(conn, "node", node_id))
    finally:
        engine.dispose()

    command.downgrade(cfg, _PRE_ORIGIN_REVISION)
    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            assert dict(_row(conn, "node", node_id)) == stamped
    finally:
        engine.dispose()
