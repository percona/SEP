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

"""Tests for the Tasks-track taskhistory_log_state nomad-cursor migration."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app.tasks.config import tasks_settings

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# The merged head immediately before nomad_offset / allocation_epoch are added
# (later renamed to producer_fetch_offset / producer_epoch).
_PRE_NOMAD_CURSOR_REVISION = "f028a195fbda"
# An anonymized-stream row: producer_offset diverges from the true raw offset,
# so the backfill (originally nomad_offset = producer_offset) is the documented
# approximation rather than an exact seed.
_ANONYMIZED_PRODUCER_OFFSET = 4096

_INSERT_STATE_ROW = (
    "INSERT INTO taskhistory_log_state "
    "(created_at, task_history_id, source, stream, persisted_offset, "
    "producer_offset, staging, staging_updated_at, version) "
    "VALUES ('2026-01-01 00:00:00', 1, 'run-script', 'STDOUT', 0, ?, X'', "
    "'2026-01-01 00:00:00', 0)"
)


@pytest.fixture
def tasks_alembic_config(tmp_path, monkeypatch):
    """Return an Alembic ``Config`` and sync URL pointing at a temp SQLite file."""
    db_path = tmp_path / "test_tasks.sqlite"
    sync_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(tasks_settings.DATABASE, "HOST", "")
    monkeypatch.setattr(tasks_settings.DATABASE, "NAME", str(db_path))

    cfg = Config(str(ALEMBIC_INI), ini_section="tasks")
    return cfg, sync_url


def test_backfill_seeds_producer_fetch_offset_from_producer_offset(
    tasks_alembic_config,
):
    """Assert the upgrade backfills producer_fetch_offset from producer_offset for in-flight rows."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _PRE_NOMAD_CURSOR_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(_INSERT_STATE_ROW, (_ANONYMIZED_PRODUCER_OFFSET,))
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            row = conn.exec_driver_sql(
                "SELECT producer_fetch_offset, producer_epoch FROM taskhistory_log_state"
            ).one()
        assert row.producer_fetch_offset == _ANONYMIZED_PRODUCER_OFFSET
        assert row.producer_epoch == 0
    finally:
        engine.dispose()


def test_new_columns_default_zero_on_fresh_insert(tasks_alembic_config):
    """Assert a row inserted after the upgrade defaults both new columns to 0."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(_INSERT_STATE_ROW, (0,))
            row = conn.exec_driver_sql(
                "SELECT producer_fetch_offset, producer_epoch FROM taskhistory_log_state"
            ).one()
        assert row.producer_fetch_offset == 0
        assert row.producer_epoch == 0
    finally:
        engine.dispose()
