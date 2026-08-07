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
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_SERVICE_ID_REVISION = "b7c8d9e0f1a2"
_PRE_SERVICE_ID_REVISION = "f0a1b2c3d4e5"
_TABLE = "mysql_backup_run"
_INDEX = "ix_mysql_backup_run_service_id"


def _run_state(sync_url: str) -> tuple[set[str], set[str]]:
    """Return column names and index names on ``mysql_backup_run``.

    :param sync_url: Sync SQLAlchemy URL of the migrated test database.
    :return: The table's column names and index names, both empty when it does
        not exist.
    """
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        if _TABLE not in inspector.get_table_names():
            return set(), set()
        return (
            {column["name"] for column in inspector.get_columns(_TABLE)},
            {index["name"] for index in inspector.get_indexes(_TABLE)},
        )
    finally:
        engine.dispose()


def _add_service_id_by_hand(sync_url: str) -> None:
    """Add ``service_id`` outside the migration chain.

    :param sync_url: Sync SQLAlchemy URL of the migrated test database.
    """
    engine = create_engine(sync_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN service_id INT"))
    finally:
        engine.dispose()


def _drop_run_table_by_hand(sync_url: str) -> None:
    """Drop ``mysql_backup_run`` outside the migration chain.

    :param sync_url: Sync SQLAlchemy URL of the migrated test database.
    """
    engine = create_engine(sync_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TABLE {_TABLE}"))
    finally:
        engine.dispose()


class TestServiceIdMigration:
    """Define tests for the ``service_id`` column and index revision."""

    def test_upgrade_adds_service_id_column(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert upgrade stamps ``service_id`` onto ``mysql_backup_run``."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _SERVICE_ID_REVISION)

        columns, _ = _run_state(sync_url)

        assert "service_id" in columns

    def test_upgrade_indexes_service_id(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert upgrade indexes ``service_id``, the new per-service query key."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _SERVICE_ID_REVISION)

        _, indexes = _run_state(sync_url)

        assert _INDEX in indexes

    def test_downgrade_drops_service_id_column_and_index(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert downgrade removes both the column and its index."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _SERVICE_ID_REVISION)
        command.downgrade(cfg, _PRE_SERVICE_ID_REVISION)

        columns, indexes = _run_state(sync_url)

        assert "service_id" not in columns
        assert _INDEX not in indexes

    def test_upgrade_skips_a_table_that_already_carries_the_column(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert upgrade no-ops instead of failing when the column already exists.

        The revision guards on ``sa.inspect`` because an installation whose schema
        was created from the models rather than replayed from the chain already
        carries the column when this revision runs. Simulated by adding it by hand
        at the previous revision, which an unguarded ``add_column`` would then fail
        on.
        """
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _PRE_SERVICE_ID_REVISION)
        _add_service_id_by_hand(sync_url)

        command.upgrade(cfg, _SERVICE_ID_REVISION)

        columns, _ = _run_state(sync_url)

        assert "service_id" in columns

    def test_upgrade_backfills_the_index_when_only_the_column_exists(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert upgrade still indexes a column added outside the chain."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _PRE_SERVICE_ID_REVISION)
        _add_service_id_by_hand(sync_url)

        command.upgrade(cfg, _SERVICE_ID_REVISION)

        _, indexes = _run_state(sync_url)

        assert _INDEX in indexes

    def test_upgrade_no_ops_when_the_table_is_absent(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert upgrade skips a schema with no ``mysql_backup_run`` at all.

        ``_table_state`` reports an absent table as two empty sets, which the
        column guard alone would read as "column missing" and run ``add_column``
        against nothing. Unreachable through the linear chain, so simulated by
        dropping the table by hand at the previous revision; the point is that
        upgrade honours the same absent-table contract downgrade does.
        """
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _PRE_SERVICE_ID_REVISION)
        _drop_run_table_by_hand(sync_url)

        command.upgrade(cfg, _SERVICE_ID_REVISION)

        assert _run_state(sync_url) == (set(), set())

    def test_downgrade_drops_the_column_when_the_index_is_already_gone(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert downgrade tolerates a schema whose index was dropped by hand."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _SERVICE_ID_REVISION)

        engine = create_engine(sync_url)
        try:
            with engine.begin() as connection:
                connection.execute(text(f"DROP INDEX {_INDEX}"))
        finally:
            engine.dispose()

        command.downgrade(cfg, _PRE_SERVICE_ID_REVISION)

        columns, _ = _run_state(sync_url)

        assert "service_id" not in columns
