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

"""create atw send log table

Revision ID: c93998e0fa14
Revises: b82887dfe93d
Create Date: 2026-07-24 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "c93998e0fa14"
down_revision: Union[str, None] = "b82887dfe93d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "atw_send_log" not in existing_tables:
        op.create_table(
            "atw_send_log",
            sa.Column("id", sa.Uuid(), autoincrement=False, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("incident_id", sa.Uuid(), nullable=False),
            sa.Column("case_ref", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "requested_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column(
                "status",
                sa.Enum(
                    "PENDING",
                    "RUNNING",
                    "SUCCESS",
                    "FAILED",
                    name="atwsendstatusenum",
                    native_enum=False,
                    create_constraint=True,
                ),
                nullable=False,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(
                ["incident_id"], ["atw_incident.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_atw_send_log_incident_id"),
            "atw_send_log",
            ["incident_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "atw_send_log" in existing_tables:
        op.drop_index(
            op.f("ix_atw_send_log_incident_id"), table_name="atw_send_log"
        )
        op.drop_table("atw_send_log")
