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

"""Define tests for the MySQL backup catalog ``service_id`` column migration."""

from alembic import command
from sqlalchemy import create_engine, inspect, text

_SERVICE_ID_REVISION = "b7c8d9e0f1a2"
_PRE_SERVICE_ID_REVISION = "f0a1b2c3d4e5"
_TABLE = "mysql_backup_run"
_INDEX = "ix_mysql_backup_run_service_id"


def _run_columns(sync_url: str) -> set[str]:
    """Return column names on ``mysql_backup_run``, or empty if absent.

    :param sync_url: Sync SQLAlchemy URL of the migrated test database.
    :return: The table's column names, or an empty set when it does not exist.
    """
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        if _TABLE not in inspector.get_table_names():
            return set()
        return {column["name"] for column in inspector.get_columns(_TABLE)}
    finally:
        engine.dispose()


def _run_indexes(sync_url: str) -> set[str]:
    """Return index names on ``mysql_backup_run``, or empty if absent.

    :param sync_url: Sync SQLAlchemy URL of the migrated test database.
    :return: The table's index names, or an empty set when it does not exist.
    """
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        if _TABLE not in inspector.get_table_names():
            return set()
        return {index["name"] for index in inspector.get_indexes(_TABLE)}
    finally:
        engine.dispose()


def test_upgrade_adds_service_id_column(sep_alembic_config):
    """Assert upgrade stamps ``service_id`` onto ``mysql_backup_run``."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _SERVICE_ID_REVISION)
    assert "service_id" in _run_columns(sync_url)


def test_upgrade_indexes_service_id(sep_alembic_config):
    """Assert upgrade indexes ``service_id``, the new per-service query key."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _SERVICE_ID_REVISION)
    assert _INDEX in _run_indexes(sync_url)


def test_downgrade_drops_service_id_column_and_index(sep_alembic_config):
    """Assert downgrade removes both the column and its index."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _SERVICE_ID_REVISION)
    command.downgrade(cfg, _PRE_SERVICE_ID_REVISION)

    assert "service_id" not in _run_columns(sync_url)
    assert _INDEX not in _run_indexes(sync_url)


def test_upgrade_skips_a_table_that_already_carries_the_column(sep_alembic_config):
    """Assert upgrade no-ops instead of failing when the column already exists.

    The revision guards on ``sa.inspect`` because an installation whose schema was
    created from the models rather than replayed from the chain already carries the
    column when this revision runs. Simulated by adding it by hand at the previous
    revision, which an unguarded ``add_column`` would then fail on.
    """
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _PRE_SERVICE_ID_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN service_id INT"))
    finally:
        engine.dispose()

    command.upgrade(cfg, _SERVICE_ID_REVISION)

    assert "service_id" in _run_columns(sync_url)
