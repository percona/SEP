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

"""Create taskhistory_log and taskhistory_log_state tables.

Revision ID: taskhistory_log_tables
Revises: bb3edb973603
Create Date: 2026-04-14 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "taskhistory_log_tables"
down_revision: Union[str, None] = "bb3edb973603"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "taskhistory_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("task_history_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "stream",
            sa.Enum("STDOUT", "STDERR", name="tasklogtype", native_enum=False),
            nullable=False,
        ),
        sa.Column("start_offset", sa.BigInteger(), nullable=False),
        sa.Column("end_offset", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_history_id"],
            ["taskhistory.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_history_id",
            "source",
            "stream",
            "start_offset",
            name="uq_taskhistory_log_chunk",
        ),
    )
    op.create_index(
        "ix_taskhistory_log_lookup",
        "taskhistory_log",
        ["task_history_id", "source", "stream", "start_offset"],
        unique=False,
    )
    op.create_index(
        op.f("ix_taskhistory_log_task_history_id"),
        "taskhistory_log",
        ["task_history_id"],
        unique=False,
    )

    op.create_table(
        "taskhistory_log_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("task_history_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "stream",
            sa.Enum("STDOUT", "STDERR", name="tasklogtype", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "persisted_offset",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "producer_offset",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "staging",
            sa.LargeBinary(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "staging_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["task_history_id"],
            ["taskhistory.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_history_id",
            "source",
            "stream",
            name="uq_taskhistory_log_state_stream",
        ),
    )
    op.create_index(
        op.f("ix_taskhistory_log_state_task_history_id"),
        "taskhistory_log_state",
        ["task_history_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_taskhistory_log_state_task_history_id"),
        table_name="taskhistory_log_state",
    )
    op.drop_table("taskhistory_log_state")
    op.drop_index("ix_taskhistory_log_task_history_id", table_name="taskhistory_log")
    op.drop_index("ix_taskhistory_log_lookup", table_name="taskhistory_log")
    op.drop_table("taskhistory_log")
