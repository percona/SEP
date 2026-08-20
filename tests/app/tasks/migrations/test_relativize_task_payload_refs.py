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

"""Tests for the Tasks-track relativize-task-payload-refs data migration."""

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app.tasks.config import tasks_settings

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# The head immediately before payload references are relativized.
_PRE_RELATIVIZE_REVISION = "d25887ee3fea"

_INSERT_TASK = (
    "INSERT INTO task "
    "(created_at, updated_at, name, data, backend, owner, "
    "is_template, protected, alert_on_fail) "
    "VALUES ('2026-01-01 00:00:00', '2026-01-01 00:00:00', ?, ?, "
    "'PROXY', 'BACKUPS', 0, 0, 0)"
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


def _seed(conn, name, data):
    """Insert a PROXY ``task`` row with the given name and JSON ``data``."""
    conn.exec_driver_sql(_INSERT_TASK, (name, json.dumps(data)))


def _payload_of(conn, name):
    """Return the ``data['payload']`` (or ``None``) for the named task row."""
    row = conn.exec_driver_sql("SELECT data FROM task WHERE name = ?", (name,)).one()
    return json.loads(row.data).get("payload")


def _proxy(payload=None):
    """Build a minimal PROXY task ``data`` dict, optionally with a payload."""
    data = {"task": "run-python"}
    if payload is not None:
        data["payload"] = payload
    return data


def test_heals_all_three_mysql_backup_types(tasks_alembic_config):
    """Assert stale binlog/xtrabackup/mydumper refs heal to relative mysql_backups refs."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _PRE_RELATIVIZE_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            for backup_type in ("binlog", "xtrabackup", "mydumper"):
                _seed(
                    conn,
                    f"{backup_type}-task",
                    _proxy(
                        "file:///srv/deploy/app/sep/plugins/backup/"
                        f"{backup_type}_payload"
                    ),
                )
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            for backup_type in ("binlog", "xtrabackup", "mydumper"):
                assert _payload_of(conn, f"{backup_type}-task") == (
                    f"file://app/sep/plugins/mysql_backups/{backup_type}_payload"
                )
    finally:
        engine.dispose()


def test_heals_doubled_app_prefix(tasks_alembic_config):
    """Assert a doubled ``.../app/app/sep/...`` prefix slices from the last package segment."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _PRE_RELATIVIZE_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            _seed(
                conn,
                "doubled-task",
                _proxy("file:///opt/app/app/sep/plugins/backup/binlog_payload"),
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            assert _payload_of(conn, "doubled-task") == (
                "file://app/sep/plugins/mysql_backups/binlog_payload"
            )
    finally:
        engine.dispose()


def test_heals_apps_backup_form(tasks_alembic_config):
    """Assert the post-forward-port ``apps/backup/`` form heals to ``apps/mysql_backups/``."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _PRE_RELATIVIZE_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            _seed(
                conn,
                "apps-task",
                _proxy("file:///srv/app/sep/apps/backup/binlog_payload"),
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            assert _payload_of(conn, "apps-task") == (
                "file://app/sep/apps/mysql_backups/binlog_payload"
            )
    finally:
        engine.dispose()


def test_heals_prefix_containing_app_sep_substring(tasks_alembic_config):
    """Assert a deploy prefix that itself contains ``app/sep/`` slices from the last segment."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _PRE_RELATIVIZE_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            _seed(
                conn,
                "myapp-task",
                _proxy(
                    "file:///srv/myapp/sep/releases/v1/app/sep/plugins/backup/binlog_payload"
                ),
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            assert _payload_of(conn, "myapp-task") == (
                "file://app/sep/plugins/mysql_backups/binlog_payload"
            )
    finally:
        engine.dispose()


def test_relativizes_non_backup_plugin_without_renaming(tasks_alembic_config):
    """Assert a non-mysql plugin ref is relativized but its plugin dir is not renamed."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _PRE_RELATIVIZE_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            _seed(
                conn,
                "pg-task",
                _proxy("file:///srv/deploy/app/sep/plugins/backup_pg/pg_payload"),
            )
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            assert _payload_of(conn, "pg-task") == (
                "file://app/sep/plugins/backup_pg/pg_payload"
            )
    finally:
        engine.dispose()


def test_leaves_unrelated_rows_untouched(tasks_alembic_config):
    """Assert non-app/sep payloads and payload-less rows are left unchanged."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _PRE_RELATIVIZE_REVISION)

    other_payload = "file:///opt/vendor/scripts/payload"
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            _seed(conn, "other-task", _proxy(other_payload))
            _seed(conn, "no-payload-task", _proxy())
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            assert _payload_of(conn, "other-task") == other_payload
            assert _payload_of(conn, "no-payload-task") is None
    finally:
        engine.dispose()


def test_is_idempotent(tasks_alembic_config):
    """Assert an already-healed relative ref is left unchanged by the upgrade."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _PRE_RELATIVIZE_REVISION)

    healed = "file://app/sep/plugins/mysql_backups/binlog_payload"
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            _seed(conn, "binlog-task", _proxy(healed))
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            assert _payload_of(conn, "binlog-task") == healed
    finally:
        engine.dispose()
