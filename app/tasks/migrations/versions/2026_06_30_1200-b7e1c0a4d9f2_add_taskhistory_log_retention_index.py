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

"""Add taskhistory effective-completion index for log retention purges

Revision ID: b7e1c0a4d9f2
Revises: 2f5a00236369, abc65df0318a, c4e8f0a3b1d2
Create Date: 2026-06-30 12:00:00.000000

Merge the three outstanding tasks-track heads into a single head and add a
partial expression index that supports the periodic task-history-log purge
(SEP-1474).

The purge selects aged, no-longer-active executions by
``COALESCE(finished_at, started_at, created_at) < cutoff`` filtered to
non-active statuses. The ``COALESCE`` expression is not covered by the plain
``finished_at`` column, so a functional index is created on it, made *partial*
on ``status NOT IN ('PENDING', 'RUNNING')`` so the index only carries the
purgeable rows it is scanned for. ``EnumField(..., native_enum=False)`` persists
the enum *names*, hence the uppercase status literals in the predicate.

PostgreSQL uses ``CREATE INDEX CONCURRENTLY`` inside an autocommit block so
index creation does not block concurrent dispatches. SQLite (dev/tests only)
uses plain ``CREATE INDEX``; it supports partial and expression indexes. MySQL
is a no-op: the tasks service runs on PostgreSQL in production and MySQL is a
dev-only target where an unindexed purge scan is acceptable.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b7e1c0a4d9f2"
down_revision: Union[str, Sequence[str], None] = (
    "2f5a00236369",
    "abc65df0318a",
    "c4e8f0a3b1d2",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "ix_taskhistory_effective_completion"
_INDEX_EXPR = "COALESCE(finished_at, started_at, created_at)"
_PARTIAL_WHERE = "status NOT IN ('PENDING', 'RUNNING')"


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} "
                f"ON taskhistory (({_INDEX_EXPR})) WHERE {_PARTIAL_WHERE}"
            )
    elif dialect == "sqlite":
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} "
            f"ON taskhistory ({_INDEX_EXPR}) WHERE {_PARTIAL_WHERE}"
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
    elif dialect == "sqlite":
        op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
