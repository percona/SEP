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

"""add service_id to mysql_backup_run

Revision ID: b7c8d9e0f1a2
Revises: f0a1b2c3d4e5
Create Date: 2026-08-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_service_id(bind: Connection) -> bool:
    """Return whether ``mysql_backup_run.service_id`` already exists.

    :param bind: The active migration connection.
    :return: ``True`` when the table exists and already carries the column.
    """
    inspector = sa.inspect(bind)
    if "mysql_backup_run" not in inspector.get_table_names():
        return False
    return any(
        column["name"] == "service_id"
        for column in inspector.get_columns("mysql_backup_run")
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _has_service_id(bind):
        return
    op.add_column(
        "mysql_backup_run", sa.Column("service_id", sa.Integer(), nullable=True)
    )
    op.create_index(
        op.f("ix_mysql_backup_run_service_id"),
        "mysql_backup_run",
        ["service_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_service_id(bind):
        return
    op.drop_index(
        op.f("ix_mysql_backup_run_service_id"), table_name="mysql_backup_run"
    )
    op.drop_column("mysql_backup_run", "service_id")
