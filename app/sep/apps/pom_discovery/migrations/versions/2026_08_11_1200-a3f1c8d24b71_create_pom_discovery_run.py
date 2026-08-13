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

"""create pom discovery run table

Revision ID: a3f1c8d24b71
Revises:
Create Date: 2026-08-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a3f1c8d24b71"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = ("pom_discovery",)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()

    if "pom_discovery_run" in existing_tables:
        return

    op.create_table(
        "pom_discovery_run",
        sa.Column("id", sa.Uuid(), autoincrement=False, nullable=False),
        # BaseUUIDSQLModel's own columns. Omitting them is the mistake that makes the
        # table exist and every query against it fail.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            # The enum's member NAMES, not its values: SQLAlchemy's non-native Enum
            # persists by name, so a constraint listing the lowercase values rejects
            # every insert the model makes.
            sa.Enum(
                "RUNNING",
                "SUCCESS",
                "PARTIAL",
                "FAILED",
                name="proberunstatus",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("services_total", sa.Integer(), nullable=False),
        sa.Column("services_resolved", sa.Integer(), nullable=False),
        sa.Column("services_orphaned", sa.Integer(), nullable=False),
        sa.Column("services_answered", sa.Integer(), nullable=False),
        sa.Column(
            "facts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "nodes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pom_discovery_run_started_at"),
        "pom_discovery_run",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pom_discovery_run_status"),
        "pom_discovery_run",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pom_discovery_run_status"), table_name="pom_discovery_run")
    op.drop_index(
        op.f("ix_pom_discovery_run_started_at"), table_name="pom_discovery_run"
    )
    op.drop_table("pom_discovery_run")
