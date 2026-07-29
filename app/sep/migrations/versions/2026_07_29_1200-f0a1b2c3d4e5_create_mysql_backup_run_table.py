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

"""create mysql_backup_run table

Revision ID: f0a1b2c3d4e5
Revises: a2b3c4d5e6f7
Create Date: 2026-07-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mysql_backup_run",
        sa.Column("task_history_id", sa.Integer(), nullable=False),
        sa.Column("service_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("hostname", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("backup_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("location", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "upload_destination", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mysql_backup_run_service_name"),
        "mysql_backup_run",
        ["service_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mysql_backup_run_task_history_id"),
        "mysql_backup_run",
        ["task_history_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mysql_backup_run_task_history_id"), table_name="mysql_backup_run"
    )
    op.drop_index(
        op.f("ix_mysql_backup_run_service_name"), table_name="mysql_backup_run"
    )
    op.drop_table("mysql_backup_run")
