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

"""create atw incident tables

Revision ID: b82887dfe93d
Revises:
Create Date: 2026-07-20 12:38:23.918879

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "b82887dfe93d"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = ("atw",)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "atw_incident" not in existing_tables:
        op.create_table(
            "atw_incident",
            sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "case_ref", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column("id", sa.Uuid(), autoincrement=False, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    if "atw_incident_execution" not in existing_tables:
        op.create_table(
            "atw_incident_execution",
            sa.Column("id", sa.Uuid(), autoincrement=False, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("incident_id", sa.Uuid(), nullable=False),
            sa.Column("task_history_id", sa.Integer(), nullable=False),
            sa.Column(
                "snippet_filename", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.ForeignKeyConstraint(
                ["incident_id"], ["atw_incident.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "incident_id",
                "task_history_id",
                name="uq_atw_incident_execution_incident_task",
            ),
        )
        op.create_index(
            op.f("ix_atw_incident_execution_task_history_id"),
            "atw_incident_execution",
            ["task_history_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "atw_incident_execution" in existing_tables:
        op.drop_index(
            op.f("ix_atw_incident_execution_task_history_id"),
            table_name="atw_incident_execution",
        )
        op.drop_table("atw_incident_execution")
    if "atw_incident" in existing_tables:
        op.drop_table("atw_incident")
