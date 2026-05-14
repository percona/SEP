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

"""Add filelock requirement to backup tasks

Revision ID: add_filelock_to_backups
Revises: 0b852d9798ef
Create Date: 2025-12-29 10:01:00.000000

"""
import logging
import yaml
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'add_filelock_to_backups'
down_revision: Union[str, None] = '0b852d9798ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger(__name__)


def _task_table() -> sa.Table:
    return sa.Table(
        "task",
        sa.MetaData(),
        sa.Column("id", sa.Integer()),
        sa.Column("data", sa.JSON()),
        sa.Column("owner", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("backend", sa.Enum("NOMAD", "PROXY", name="taskbackendenum", native_enum=False)),
    )


def _is_mydumper_or_xtrabackup(data: dict) -> bool:
    """Check if the task is a MYDUMPER or XTRABACKUP backup task."""
    try:
        if data.get("task") != "run-python":
            return False

        meta = data.get("meta", {})
        config_yaml = meta.get("config", "")
        if not config_yaml:
            return False

        task_config = yaml.safe_load(config_yaml)
        server_list = task_config.get("SERVER_LIST", [])
        if not server_list:
            return False

        backup_type = server_list[0].get("BACKUP_TYPE", "")
        # BackupType.MYDUMPER = "M", BackupType.XTRABACKUP = "X"
        return backup_type in ("M", "X")
    except Exception:
        logger.exception("Error checking backup type")
        return False


def _add_filelock_requirement(requirements: str) -> str:
    """Add filelock to requirements if not already present."""
    if not requirements:
        return "filelock"

    req_list = [req.strip() for req in requirements.split("\n") if req.strip()]
    if "filelock" not in req_list:
        req_list.append("filelock")

    return "\n".join(req_list)


def upgrade() -> None:
    """Add filelock requirement to existing MYDUMPER and XTRABACKUP backup tasks."""
    task_table = _task_table()
    conn = op.get_bind()

    rows = conn.execute(
        sa.select(
            task_table.c.id,
            task_table.c.data,
        ).where(
            task_table.c.owner == "BACKUPS",
            task_table.c.backend == "PROXY",
        )
    ).fetchall()

    updated_count = 0
    for id_, data in rows:
        if not data or not isinstance(data, dict):
            continue

        try:
            if not _is_mydumper_or_xtrabackup(data):
                continue

            meta = data.get("meta", {})
            current_requirements = meta.get("requirements", "")

            if "filelock" in current_requirements:
                # Already has filelock, skip
                continue

            # Add filelock to requirements
            updated_requirements = _add_filelock_requirement(current_requirements)

            # Update the data
            new_data = data.copy()
            new_data["meta"] = meta.copy()
            new_data["meta"]["requirements"] = updated_requirements

            conn.execute(
                task_table.update()
                .where(task_table.c.id == id_)
                .values(data=new_data)
            )
            updated_count += 1
            logger.info("Updated task id=%s with filelock requirement", id_)
        except Exception:
            logger.exception("Failed to update task id=%s", id_)
            continue

    logger.info("Migration completed. Updated %d backup tasks with filelock requirement.", updated_count)


def downgrade() -> None:
    """Remove filelock requirement from backup tasks (optional rollback)."""
    task_table = _task_table()
    conn = op.get_bind()

    rows = conn.execute(
        sa.select(
            task_table.c.id,
            task_table.c.data,
        ).where(
            task_table.c.owner == "BACKUPS",
            task_table.c.backend == "PROXY",
        )
    ).fetchall()

    for id_, data in rows:
        if not data or not isinstance(data, dict):
            continue

        try:
            if not _is_mydumper_or_xtrabackup(data):
                continue

            meta = data.get("meta", {})
            current_requirements = meta.get("requirements", "")

            if "filelock" not in current_requirements:
                continue

            # Remove filelock from requirements
            req_list = [req.strip() for req in current_requirements.split("\n") if req.strip() and req.strip() != "filelock"]
            updated_requirements = "\n".join(req_list)

            # Update the data
            new_data = data.copy()
            new_data["meta"] = meta.copy()
            new_data["meta"]["requirements"] = updated_requirements

            conn.execute(
                task_table.update()
                .where(task_table.c.id == id_)
                .values(data=new_data)
            )
            logger.info("Removed filelock requirement from task id=%s", id_)
        except Exception:
            logger.exception("Failed to downgrade task id=%s", id_)
            continue
