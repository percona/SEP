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

"""Tests for the ATW ``closed_at`` column Alembic migration."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.sep.config import sep_settings

REPO_ROOT = Path(__file__).resolve().parents[5]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATION_PATH = (
    REPO_ROOT
    / "app"
    / "sep"
    / "apps"
    / "atw"
    / "migrations"
    / "versions"
    / "2026_07_30_1200-447ee0172734_add_atw_incident_closed_at.py"
)

_CLOSED_AT_REVISION = "447ee0172734"
_PRE_CLOSED_AT_REVISION = "c93998e0fa14"


def _load_migration():
    """Import the closed_at migration module from its file path."""
    spec = importlib.util.spec_from_file_location(
        "atw_closed_at_migration", MIGRATION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sep_alembic_config(tmp_path, monkeypatch):
    """Yield an Alembic ``Config`` pointing at a temp SQLite file.

    :param tmp_path: Pytest's per-test temporary directory.
    :param monkeypatch: Pytest monkeypatch fixture.
    :return: A tuple of (Config, sync sqlite URL) for the test DB.
    """
    db_path = tmp_path / "test_atw_closed_at.sqlite"
    sync_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(sep_settings.DATABASE, "HOST", "")
    monkeypatch.setattr(sep_settings.DATABASE, "NAME", str(db_path))

    cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    return cfg, sync_url


def _incident_columns(sync_url: str) -> set[str]:
    """Return column names on ``atw_incident``, or empty if the table is absent."""
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        if "atw_incident" not in inspector.get_table_names():
            return set()
        return {column["name"] for column in inspector.get_columns("atw_incident")}
    finally:
        engine.dispose()


def test_upgrade_adds_closed_at_column(sep_alembic_config):
    """Assert upgrade stamps ``closed_at`` onto ``atw_incident``."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _CLOSED_AT_REVISION)
    assert "closed_at" in _incident_columns(sync_url)


def test_downgrade_drops_closed_at_column(sep_alembic_config):
    """Assert downgrade removes ``closed_at`` from ``atw_incident``."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _CLOSED_AT_REVISION)
    command.downgrade(cfg, _PRE_CLOSED_AT_REVISION)
    assert "closed_at" not in _incident_columns(sync_url)


class TestClosedAtMigrationGuards:
    """Exercise idempotent guards that Alembic heads alone never hit."""

    def test_upgrade_returns_early_without_incident_table(self) -> None:
        """Skip adding the column when ``atw_incident`` does not exist."""
        migration = _load_migration()
        inspector = MagicMock()
        inspector.get_table_names.return_value = []

        with (
            patch.object(migration.op, "get_bind", return_value=MagicMock()),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(migration.op, "add_column") as add_column,
        ):
            migration.upgrade()

        add_column.assert_not_called()

    def test_upgrade_skips_when_column_already_present(self) -> None:
        """Leave ``atw_incident`` alone when ``closed_at`` is already there."""
        migration = _load_migration()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["atw_incident"]
        inspector.get_columns.return_value = [{"name": "closed_at"}]

        with (
            patch.object(migration.op, "get_bind", return_value=MagicMock()),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(migration.op, "add_column") as add_column,
        ):
            migration.upgrade()

        add_column.assert_not_called()

    def test_downgrade_returns_early_without_incident_table(self) -> None:
        """Skip dropping the column when ``atw_incident`` does not exist."""
        migration = _load_migration()
        inspector = MagicMock()
        inspector.get_table_names.return_value = []

        with (
            patch.object(migration.op, "get_bind", return_value=MagicMock()),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(migration.op, "drop_column") as drop_column,
        ):
            migration.downgrade()

        drop_column.assert_not_called()

    def test_downgrade_skips_when_column_absent(self) -> None:
        """Leave ``atw_incident`` alone when ``closed_at`` is already gone."""
        migration = _load_migration()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["atw_incident"]
        inspector.get_columns.return_value = [{"name": "id"}]

        with (
            patch.object(migration.op, "get_bind", return_value=MagicMock()),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(migration.op, "drop_column") as drop_column,
        ):
            migration.downgrade()

        drop_column.assert_not_called()

    def test_downgrade_drops_closed_at_column(self) -> None:
        """Drop ``closed_at`` when the table and column both exist."""
        migration = _load_migration()
        inspector = MagicMock()
        inspector.get_table_names.return_value = ["atw_incident"]
        inspector.get_columns.return_value = [{"name": "closed_at"}]

        with (
            patch.object(migration.op, "get_bind", return_value=MagicMock()),
            patch.object(migration.sa, "inspect", return_value=inspector),
            patch.object(migration.op, "drop_column") as drop_column,
        ):
            migration.downgrade()

        drop_column.assert_called_once_with("atw_incident", "closed_at")
