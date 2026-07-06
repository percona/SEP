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

"""Relativize task payload references and heal orphaned backup rows

Revision ID: 13e897d11734
Revises: d25887ee3fea
Create Date: 2026-07-06 19:00:00.000000

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "13e897d11734"
down_revision: Union[str, None] = "d25887ee3fea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger(__name__)

_MARKER = "app/sep/"
_BACKUP_DIR_RENAMES = {
    "app/sep/plugins/backup/": "app/sep/plugins/mysql_backups/",
    "app/sep/plugins/backups/": "app/sep/plugins/mysql_backups/",
    "app/sep/apps/backup/": "app/sep/apps/mysql_backups/",
    "app/sep/apps/backups/": "app/sep/apps/mysql_backups/",
}


def _task_table() -> sa.Table:
    return sa.Table(
        "task",
        sa.MetaData(),
        sa.Column("id", sa.Integer()),
        sa.Column("data", sa.JSON()),
        sa.Column(
            "backend",
            sa.Enum("NOMAD", "PROXY", "CELERY", name="taskbackendenum", native_enum=False),
        ),
    )


def _relativize_payload_reference(payload: str) -> str | None:
    """Return the healed, repo-relative reference, or ``None`` when unchanged.

    Slice from the last ``app/sep/`` package segment (robust to any deployment
    root — including one whose prefix itself contains ``app/sep/``, e.g.
    ``/srv/myapp/sep/...`` — and to the doubled ``.../app/app/sep/...`` prefix),
    heal the retired ``backup(s)`` backup dir to ``mysql_backups`` under both
    package layouts, and return a ``file://<package-relative>`` reference. Rows
    without a package segment, or already in the healed form, return ``None``.

    :param payload: The stored ``file://`` payload reference to normalize.
    :return: The healed relative reference, or ``None`` if no change is needed.
    """
    if not payload.startswith("file://"):
        return None
    raw = payload[len("file://") :]
    index = raw.rfind(_MARKER)
    if index == -1:
        return None
    relative = raw[index:]
    for old, new in _BACKUP_DIR_RENAMES.items():
        if relative.startswith(old):
            relative = new + relative[len(old) :]
            break
    new_payload = f"file://{relative}"
    return new_payload if new_payload != payload else None


def upgrade() -> None:
    """Rewrite stored PROXY task payloads to repo-relative references and heal backups."""
    task_table = _task_table()
    conn = op.get_bind()

    rows = conn.execute(
        sa.select(
            task_table.c.id,
            task_table.c.data,
        ).where(
            task_table.c.backend == "PROXY",
        )
    ).fetchall()

    updated_count = 0
    for id_, data in rows:
        if not isinstance(data, dict):
            continue

        payload = data.get("payload")
        if not isinstance(payload, str):
            continue

        new_payload = _relativize_payload_reference(payload)
        if new_payload is None:
            continue

        new_data = dict(data)
        new_data["payload"] = new_payload
        conn.execute(
            task_table.update().where(task_table.c.id == id_).values(data=new_data)
        )
        updated_count += 1
        logger.info("Relativized payload reference for task id=%s", id_)

    logger.info(
        "Migration complete. Relativized %d task payload references.", updated_count
    )


def downgrade() -> None:
    """Return without rolling back; path normalization is not meaningfully reversible.

    The upgrade collapses several equivalent absolute forms (and the retired
    ``backup`` dir name) onto one canonical relative reference, discarding the
    original deployment-absolute prefix, so there is no unique earlier value to
    restore. The relative references remain resolvable by the current code.
    """
