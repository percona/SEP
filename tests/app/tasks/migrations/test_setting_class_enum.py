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

"""Tests for the Tasks-track setting_class enum-extension migration."""

import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from app.core.db.utils import check_constraint_name
from app.tasks.config import tasks_settings

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# The add_setting_override_table revision on the Tasks track, before SETTINGS /
# ALERT_SETTINGS were added to the setting_class CHECK constraint.
_TASKS_PRE_ENUM_REVISION = "fafdb0445092"


@pytest.fixture
def tasks_alembic_config(tmp_path, monkeypatch):
    """Yield an Alembic ``Config`` and sync URL pointing at a temp SQLite file."""
    db_path = tmp_path / "test_tasks.sqlite"
    sync_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(tasks_settings.DATABASE, "HOST", "")
    monkeypatch.setattr(tasks_settings.DATABASE, "NAME", str(db_path))

    cfg = Config(str(ALEMBIC_INI), ini_section="tasks")
    return cfg, sync_url


def _insert_override(conn, setting_class: str) -> None:
    """Insert a minimal ``settingoverride`` row with the given setting_class."""
    conn.exec_driver_sql(
        "INSERT INTO settingoverride "
        "(created_at, setting_class, key, value, is_active) "
        "VALUES ('2026-01-01 00:00:00', ?, 'X', 'true', 1)",
        (setting_class,),
    )


def test_setting_class_enum_accepts_new_members_after_upgrade(tasks_alembic_config):
    """After ``upgrade heads``, SETTINGS and ALERT_SETTINGS rows are accepted."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, "heads")

    new_members = ("SETTINGS", "ALERT_SETTINGS")
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            for member in new_members:
                _insert_override(conn, member)
            count = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM settingoverride"
            ).scalar()
        assert count == len(new_members)
    finally:
        engine.dispose()


def test_setting_class_enum_rejects_new_members_before_upgrade(tasks_alembic_config):
    """At the pre-enum revision, a SETTINGS row violates the CHECK constraint."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _TASKS_PRE_ENUM_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn, pytest.raises(IntegrityError):
            _insert_override(conn, "SETTINGS")
    finally:
        engine.dispose()


def test_setting_class_check_is_dropped_after_upgrade(tasks_alembic_config):
    """After ``upgrade heads``, ``setting_class`` is an unconstrained string."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            unconstrained = ("UNREGISTERED_SETTINGS", "X" * 50)
            assert (
                check_constraint_name(conn, "settingoverride", "setting_class") is None
            )
            for token in unconstrained:
                _insert_override(conn, token)
            count = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM settingoverride"
            ).scalar()
        assert count == len(unconstrained)
    finally:
        engine.dispose()


def test_setting_class_check_downgrade_deletes_unknown_rows(
    tasks_alembic_config, caplog
):
    """Downgrade deletes out-of-list rows, logs the count, and restores the CHECK."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            _insert_override(conn, "UNREGISTERED_SETTINGS")
            _insert_override(conn, "SEP_SETTINGS")
    finally:
        engine.dispose()

    with caplog.at_level(logging.INFO, logger="app.core.settings_override.alembic_ops"):
        command.downgrade(cfg, "-1")

    assert "Deleted 1 settingoverride row(s)" in caplog.text

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            assert (
                check_constraint_name(conn, "settingoverride", "setting_class")
                == "settingclassenum"
            )
            remaining = conn.exec_driver_sql(
                "SELECT setting_class FROM settingoverride"
            ).fetchall()
            assert remaining == [("SEP_SETTINGS",)]
            with pytest.raises(IntegrityError):
                _insert_override(conn, "UNREGISTERED_SETTINGS")
    finally:
        engine.dispose()
