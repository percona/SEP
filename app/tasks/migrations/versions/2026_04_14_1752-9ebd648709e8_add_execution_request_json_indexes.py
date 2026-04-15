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

"""Add JSON expression indexes on taskhistory.execution_request

Revision ID: 9ebd648709e8
Revises: taskhistory_log_tables
Create Date: 2026-04-14 17:52:42.245472

Add expression indexes on ``execution_request->>'task'`` and
``execution_request->>'target'`` so dispatch dedup and task-history filter
queries can use index scans instead of evaluating the JSON extract over the
narrowed candidate set.

``payload`` is intentionally NOT indexed. ``TaskExecutionRequest.payload`` may
hold the raw parameterization body for a task, which can be large enough to
exceed PostgreSQL's btree entry size limit (~2704 bytes) and fail inserts
once a functional index is present. Dispatch dedup still compares payloads
via sequential scan over the narrow candidate set produced by the new
``task``/``target`` indexes combined with the existing
``ix_taskhistory_task_id_status`` compound index.

PostgreSQL uses ``CREATE INDEX CONCURRENTLY`` inside an autocommit block so
index creation does not block concurrent dispatches. SQLite uses plain
``CREATE INDEX`` (dev-only, effectively instantaneous). MySQL is a no-op:
MySQL 8.0 functional indexes on JSON extraction require a fixed-width ``CAST``
that changes comparison semantics (truncation), and MySQL is used only in dev
environments where unindexed JSON filtering is acceptable.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "9ebd648709e8"
down_revision: Union[str, None] = "taskhistory_log_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAMES = (
    "ix_taskhistory_exec_task",
    "ix_taskhistory_exec_target",
)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_taskhistory_exec_task "
                "ON taskhistory ((execution_request->>'task'))"
            )
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_taskhistory_exec_target "
                "ON taskhistory ((execution_request->>'target'))"
            )
    elif dialect == "sqlite":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_taskhistory_exec_task "
            "ON taskhistory (json_extract(execution_request, '$.task'))"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_taskhistory_exec_target "
            "ON taskhistory (json_extract(execution_request, '$.target'))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            for name in _INDEX_NAMES:
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    elif dialect == "sqlite":
        for name in _INDEX_NAMES:
            op.execute(f"DROP INDEX IF EXISTS {name}")
