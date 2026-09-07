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

"""Tests for the Tasks-track taskhistory failure_reason column migration."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app.tasks.config import tasks_settings
from tests.app.alembic_paths import ALEMBIC_INI

_WITH_COLUMN_REVISION = "c4b8e1f7a2d9"
_PRE_COLUMN_REVISION = "8fdfa7869662"


@pytest.fixture
def tasks_alembic_config(tmp_path, monkeypatch):
    """Return an Alembic ``Config`` and sync URL pointing at a temp SQLite file."""
    db_path = tmp_path / "test_tasks.sqlite"
    sync_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(tasks_settings.DATABASE, "HOST", "")
    monkeypatch.setattr(tasks_settings.DATABASE, "NAME", str(db_path))

    cfg = Config(str(ALEMBIC_INI), ini_section="tasks")
    return cfg, sync_url


def _task_history_columns(sync_url: str) -> set[str]:
    """Return the column names of the ``taskhistory`` table."""
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info('taskhistory')").all()
    finally:
        engine.dispose()
    return {row._mapping["name"] for row in rows}


def test_upgrade_adds_failure_reason_column(tasks_alembic_config):
    """Assert the upgrade adds the failure_reason column to the taskhistory table."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _WITH_COLUMN_REVISION)
    assert "failure_reason" in _task_history_columns(sync_url)


def test_downgrade_drops_failure_reason_column(tasks_alembic_config):
    """Assert the downgrade drops the failure_reason column from taskhistory."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _WITH_COLUMN_REVISION)
    command.downgrade(cfg, _PRE_COLUMN_REVISION)
    assert "failure_reason" not in _task_history_columns(sync_url)
