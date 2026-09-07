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

"""Tests for the executor-neutral log-cursor column rename migration."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.tasks.config import tasks_settings
from tests.app.alembic_paths import ALEMBIC_INI

_PRE_RENAME_REVISION = "a19da5cf0bca"
_RENAME_REVISION = "c8e4a2b91f70"

_FETCH_OFFSET = 4096
_PRODUCER_EPOCH = 42
_LOG_PRODUCER_EPOCH = 99


@pytest.fixture
def tasks_alembic_config(tmp_path, monkeypatch):
    """Return an Alembic ``Config`` and sync URL pointing at a temp SQLite file."""
    db_path = tmp_path / "test_tasks_rename.sqlite"
    sync_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(tasks_settings.DATABASE, "HOST", "")
    monkeypatch.setattr(tasks_settings.DATABASE, "NAME", str(db_path))

    cfg = Config(str(ALEMBIC_INI), ini_section="tasks")
    return cfg, sync_url


def test_rename_preserves_values_and_downgrades(tasks_alembic_config):
    """Assert the rename migration keeps values and restores old names on downgrade."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _PRE_RENAME_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO task "
                "(created_at, name, data, backend, owner, is_template, protected, "
                "alert_on_fail, anonymize_mask) "
                "VALUES ('2026-01-01 00:00:00', 't', '{}', 'nomad', 'ANY', 0, 0, "
                "0, 0)"
            )
            conn.exec_driver_sql(
                "INSERT INTO taskhistory "
                "(created_at, task_id, execution_request, status, "
                "log_allocation_epoch) "
                "VALUES ('2026-01-01 00:00:00', 1, '{}', 'pending', ?)",
                (_LOG_PRODUCER_EPOCH,),
            )
            conn.exec_driver_sql(
                "INSERT INTO taskhistory_log_state "
                "(created_at, task_history_id, source, stream, persisted_offset, "
                "producer_offset, nomad_offset, allocation_epoch, staging, "
                "staging_updated_at, version) "
                "VALUES ('2026-01-01 00:00:00', 1, 'run-script', 'STDOUT', 0, 0, "
                "?, ?, X'', '2026-01-01 00:00:00', 0)",
                (_FETCH_OFFSET, _PRODUCER_EPOCH),
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, _RENAME_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            state_cols = {
                c["name"] for c in inspect(conn).get_columns("taskhistory_log_state")
            }
            history_cols = {c["name"] for c in inspect(conn).get_columns("taskhistory")}
            assert "producer_fetch_offset" in state_cols
            assert "producer_epoch" in state_cols
            assert "nomad_offset" not in state_cols
            assert "allocation_epoch" not in state_cols
            assert "log_producer_epoch" in history_cols
            assert "log_allocation_epoch" not in history_cols

            state = conn.exec_driver_sql(
                "SELECT producer_fetch_offset, producer_epoch "
                "FROM taskhistory_log_state"
            ).one()
            history = conn.exec_driver_sql(
                "SELECT log_producer_epoch FROM taskhistory"
            ).one()
        assert state.producer_fetch_offset == _FETCH_OFFSET
        assert state.producer_epoch == _PRODUCER_EPOCH
        assert history.log_producer_epoch == _LOG_PRODUCER_EPOCH
    finally:
        engine.dispose()

    command.downgrade(cfg, _PRE_RENAME_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            state_cols = {
                c["name"] for c in inspect(conn).get_columns("taskhistory_log_state")
            }
            history_cols = {c["name"] for c in inspect(conn).get_columns("taskhistory")}
            assert "nomad_offset" in state_cols
            assert "allocation_epoch" in state_cols
            assert "log_allocation_epoch" in history_cols

            state = conn.exec_driver_sql(
                "SELECT nomad_offset, allocation_epoch FROM taskhistory_log_state"
            ).one()
            history = conn.exec_driver_sql(
                "SELECT log_allocation_epoch FROM taskhistory"
            ).one()
        assert state.nomad_offset == _FETCH_OFFSET
        assert state.allocation_epoch == _PRODUCER_EPOCH
        assert history.log_allocation_epoch == _LOG_PRODUCER_EPOCH
    finally:
        engine.dispose()
