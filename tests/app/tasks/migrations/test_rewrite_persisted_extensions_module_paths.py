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

"""Tests for the Tasks-track revision that moves persisted package paths forward."""

import json

from alembic import command
from sqlalchemy import create_engine

_PRE_MOVE_REVISION = "afa9bedb3b0b"
_MOVE_REVISION = "f0ee5b600303"

PRE_RENAME_MODULE = "app.sep"
"""The dotted package path rows carried before the move. A frozen literal."""

PRE_RENAME_PACKAGE = "app/sep"
"""The package directory rows carried before the move. A frozen literal."""

_INSERT_TASK = (
    "INSERT INTO task "
    "(created_at, updated_at, name, data, backend, owner, alert_detail_builder, "
    "is_template, protected, alert_on_fail) "
    "VALUES ('2026-01-01 00:00:00', '2026-01-01 00:00:00', ?, ?, "
    "'CELERY', 'ARCHIVES', ?, 0, 0, 0)"
)


def _stored(sync_url: str) -> tuple[str, dict[str, str]]:
    """Return the single task row's builder and decoded ``data``."""
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            row = conn.exec_driver_sql(
                "SELECT alert_detail_builder, data FROM task"
            ).one()
    finally:
        engine.dispose()
    return row.alert_detail_builder, json.loads(row.data)


def test_moves_every_persisted_path_forward_and_back(tasks_alembic_config):
    """Rewrite the builder, the callable and the payload URI, then restore them."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, _PRE_MOVE_REVISION)
    builder = f"{PRE_RENAME_MODULE}.apps.archives.alerts:build_owner_alert_details"
    data = {
        "callable": f"{PRE_RENAME_MODULE}.apps.inventory.sync.run",
        "payload": f"file://{PRE_RENAME_PACKAGE}/apps/archives/payload",
        "note": "left alone",
    }
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(_INSERT_TASK, ("archiver", json.dumps(data), builder))
    finally:
        engine.dispose()

    command.upgrade(cfg, _MOVE_REVISION)

    assert _stored(sync_url) == (
        "app.extensions.apps.archives.alerts:build_owner_alert_details",
        {
            "callable": "app.extensions.apps.inventory.sync.run",
            "payload": "file://app/extensions/apps/archives/payload",
            "note": "left alone",
        },
    )

    command.downgrade(cfg, _PRE_MOVE_REVISION)

    assert _stored(sync_url) == (builder, data)
