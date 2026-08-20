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

"""Tests for the Tasks-track run_result_recorder column migration."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app.tasks.config import tasks_settings

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_WITH_COLUMN_REVISION = "27a11549ef43"
_PRE_COLUMN_REVISION = "13e897d11734"


@pytest.fixture
def tasks_alembic_config(tmp_path, monkeypatch):
    """Return an Alembic ``Config`` and sync URL pointing at a temp SQLite file."""
    db_path = tmp_path / "test_tasks.sqlite"
    sync_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(tasks_settings.DATABASE, "HOST", "")
    monkeypatch.setattr(tasks_settings.DATABASE, "NAME", str(db_path))

    cfg = Config(str(ALEMBIC_INI), ini_section="tasks")
    return cfg, sync_url


def _task_columns(sync_url: str) -> set[str]:
    """Return the column names of the ``task`` table."""
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            rows = conn.exec_driver_sql("PRAGMA table_info('task')").all()
    finally:
        engine.dispose()
    return {row._mapping["name"] for row in rows}


def test_upgrade_adds_run_result_recorder_column(tasks_alembic_config):
    """Assert the upgrade adds the run_result_recorder column to the task table."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _WITH_COLUMN_REVISION)
    assert "run_result_recorder" in _task_columns(sync_url)


def test_downgrade_drops_run_result_recorder_column(tasks_alembic_config):
    """Assert the downgrade drops the run_result_recorder column from the task table."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _WITH_COLUMN_REVISION)
    command.downgrade(cfg, _PRE_COLUMN_REVISION)
    assert "run_result_recorder" not in _task_columns(sync_url)
