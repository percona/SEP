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

"""Tests for the Tasks-track taskhistory_log_state capture-status migration."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.tasks.config import tasks_settings
from app.tasks.models import LogCaptureStatusEnum, TaskHistoryLogState

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# The head immediately before capture_status is added. Cursor columns still
# use the pre-rename names ``nomad_offset`` / ``allocation_epoch``.
_PRE_CAPTURE_STATUS_REVISION = "e2f3a4b5c6d7"

_INSERT_STATE_ROW_PRE_RENAME = (
    "INSERT INTO taskhistory_log_state "
    "(created_at, task_history_id, source, stream, persisted_offset, "
    "producer_offset, nomad_offset, allocation_epoch, staging, "
    "staging_updated_at, version) "
    "VALUES ('2026-01-01 00:00:00', ?, ?, 'STDOUT', 0, ?, 0, 0, X'', "
    "'2026-01-01 00:00:00', 0)"
)

_INSERT_STATE_ROW = (
    "INSERT INTO taskhistory_log_state "
    "(created_at, task_history_id, source, stream, persisted_offset, "
    "producer_offset, producer_fetch_offset, producer_epoch, staging, "
    "staging_updated_at, version) "
    "VALUES ('2026-01-01 00:00:00', ?, ?, 'STDOUT', 0, ?, 0, 0, X'', "
    "'2026-01-01 00:00:00', 0)"
)

_SET_CAPTURE_STATUS = "UPDATE taskhistory_log_state SET capture_status = ?"

# The signature this defect leaves behind: cursors never advanced because the
# allocation was collected before the sync read it.
_STRANDED_PRODUCER_OFFSET = 0
_DRAINED_PRODUCER_OFFSET = 4096


@pytest.fixture
def tasks_alembic_config(tmp_path, monkeypatch):
    """Return an Alembic ``Config`` and sync URL pointing at a temp SQLite file."""
    db_path = tmp_path / "test_tasks.sqlite"
    sync_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(tasks_settings.DATABASE, "HOST", "")
    monkeypatch.setattr(tasks_settings.DATABASE, "NAME", str(db_path))

    cfg = Config(str(ALEMBIC_INI), ini_section="tasks")
    return cfg, sync_url


def test_pre_existing_rows_are_classified_unknown(tasks_alembic_config):
    """Assert every pre-change row is back-classified ``unknown``.

    Covers both populations the stored offsets cannot tell apart: a row stranded
    at ``producer_offset = 0`` by the lost-log defect, and one whose stream was
    genuinely drained. Neither carries evidence of which it was, so both take
    the server default rather than a guessed verdict.
    """
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _PRE_CAPTURE_STATUS_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                _INSERT_STATE_ROW_PRE_RENAME,
                (1, "run-script", _STRANDED_PRODUCER_OFFSET),
            )
            conn.exec_driver_sql(
                _INSERT_STATE_ROW_PRE_RENAME,
                (2, "clean-up", _DRAINED_PRODUCER_OFFSET),
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    # Read through the mapped type rather than the driver: the raw string
    # compares equal to the enum member either way, so only an ORM read proves
    # the backfilled value is one the column can actually load.
    engine = create_engine(sync_url)
    try:
        with Session(engine) as session:
            rows = session.execute(
                select(
                    TaskHistoryLogState.producer_offset,
                    TaskHistoryLogState.capture_status,
                ).order_by(TaskHistoryLogState.task_history_id)
            ).all()
    finally:
        engine.dispose()

    assert [row.capture_status for row in rows] == [
        LogCaptureStatusEnum.UNKNOWN,
        LogCaptureStatusEnum.UNKNOWN,
    ]
    assert [row.producer_offset for row in rows] == [
        _STRANDED_PRODUCER_OFFSET,
        _DRAINED_PRODUCER_OFFSET,
    ]


def test_upgrade_constrains_capture_status_to_the_enum_domain(tasks_alembic_config):
    """Assert the migrated column carries the enum's CHECK constraint.

    SQLite skips the implicit CHECK a non-native ``sa.Enum`` would contribute to
    ``ADD COLUMN``, warning rather than failing, so without an explicit
    constraint a DB built from migrations would accept values one built from the
    model's metadata rejects. The rejected value here is the member *value*,
    which is exactly the mistake the name-persisting column invites.
    """
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, "head")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                _INSERT_STATE_ROW, (1, "run-script", _DRAINED_PRODUCER_OFFSET)
            )
            conn.exec_driver_sql(
                _SET_CAPTURE_STATUS, (LogCaptureStatusEnum.COMPLETE.name,)
            )

        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.exec_driver_sql(
                _SET_CAPTURE_STATUS, (LogCaptureStatusEnum.COMPLETE.value,)
            )
    finally:
        engine.dispose()


def test_downgrade_drops_the_column(tasks_alembic_config):
    """Assert the downgrade removes the column and leaves the table usable."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, "head")
    command.downgrade(cfg, _PRE_CAPTURE_STATUS_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            columns = {
                row[1]
                for row in conn.exec_driver_sql(
                    "PRAGMA table_info(taskhistory_log_state)"
                ).all()
            }
            conn.exec_driver_sql(
                _INSERT_STATE_ROW_PRE_RENAME,
                (1, "run-script", _DRAINED_PRODUCER_OFFSET),
            )
    finally:
        engine.dispose()

    assert "capture_status" not in columns
