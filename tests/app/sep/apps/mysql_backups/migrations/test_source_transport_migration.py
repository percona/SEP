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

"""Define tests for the MySQL backup catalog ``source_transport`` migration."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

_TRANSPORT_REVISION = "c8d9e0f1a2b3"
_PRE_TRANSPORT_REVISION = "b7c8d9e0f1a2"
_TABLE = "mysql_backup_run"
_COLUMN = "source_transport"
_CHECK_NAME = "cataloguedsourcetransport"


def _run_state(sync_url: str) -> tuple[set[str], set[str]]:
    """Return column names and check-constraint names on ``mysql_backup_run``.

    :param sync_url: Sync SQLAlchemy URL of the migrated test database.
    :return: The table's column names and check-constraint names, both empty when
        it does not exist.
    """
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


def _insert_run(
    sync_url: str, *, source_transport: str | None, history_id: int
) -> None:
    """Insert a minimal catalog row, optionally with ``source_transport``.

    :param sync_url: Sync SQLAlchemy URL of the migrated test database.
    :param source_transport: The member name to store, or ``None`` for NULL.
    :param history_id: Unique ``task_history_id`` for the row.
    """
    engine = create_engine(sync_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO {_TABLE} "
                    "(task_history_id, backup_type, source_transport, created_at) "
                    "VALUES (:history_id, 'MYDUMPER', :source_transport, "
                    "'2026-09-18 12:00:00')"
                ),
                {"history_id": history_id, "source_transport": source_transport},
            )
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


class TestSourceTransportMigration:
    """Define tests for the ``source_transport`` column and CHECK revision."""

    def test_upgrade_adds_column_and_check(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert upgrade stamps ``source_transport`` and its CHECK constraint."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _TRANSPORT_REVISION)

        columns, checks = _run_state(sync_url)

        assert _COLUMN in columns
        assert _CHECK_NAME in checks

    def test_upgrade_check_accepts_member_names(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert the CHECK allows the enum member names the model persists."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _TRANSPORT_REVISION)

        _insert_run(sync_url, source_transport="S3", history_id=1)
        _insert_run(sync_url, source_transport="GCS", history_id=2)
        _insert_run(sync_url, source_transport=None, history_id=3)

    def test_upgrade_check_rejects_unknown_transport(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert the CHECK rejects a value outside ``S3`` / ``GCS``."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _TRANSPORT_REVISION)

        with pytest.raises(IntegrityError):
            _insert_run(sync_url, source_transport="SSH", history_id=1)

    def test_upgrade_check_rejects_wire_value(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert the CHECK stores member names, not wire values like ``s3``."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _TRANSPORT_REVISION)

        with pytest.raises(IntegrityError):
            _insert_run(sync_url, source_transport="s3", history_id=1)

    def test_downgrade_drops_column_and_check(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert downgrade removes both the column and its CHECK."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _TRANSPORT_REVISION)
        command.downgrade(cfg, _PRE_TRANSPORT_REVISION)

        columns, checks = _run_state(sync_url)

        assert _COLUMN not in columns
        assert _CHECK_NAME not in checks

    def test_upgrade_no_ops_when_the_table_is_absent(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert upgrade skips a schema with no ``mysql_backup_run`` at all."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _PRE_TRANSPORT_REVISION)
        _drop_run_table_by_hand(sync_url)

        command.upgrade(cfg, _TRANSPORT_REVISION)

        assert _run_state(sync_url) == (set(), set())

    def test_downgrade_no_ops_when_the_table_is_absent(
        self, sep_alembic_config: tuple[Config, str]
    ) -> None:
        """Assert downgrade skips when the table was already dropped."""
        cfg, sync_url = sep_alembic_config
        command.upgrade(cfg, _TRANSPORT_REVISION)
        _drop_run_table_by_hand(sync_url)

        command.downgrade(cfg, _PRE_TRANSPORT_REVISION)

        assert _run_state(sync_url) == (set(), set())
