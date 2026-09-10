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

"""Add partial retired_at indexes for the tombstone collection scan

Revision ID: d4f2a7c8b1e6
Revises: c7d1e94ab3f2
Create Date: 2026-08-26 18:00:00.000000

The collection scan selects aged tombstones by ``retired_at < cutoff`` on each
retirable table. Active rows carry ``retired_at IS NULL`` and are the
overwhelming majority, so the index is made *partial* on
``retired_at IS NOT NULL``: it then carries only the rows the scan can ever
return, and stays small no matter how large the live inventory grows.

PostgreSQL uses ``CREATE INDEX CONCURRENTLY`` inside an autocommit block so
index creation does not block the syncer writing to the same tables. SQLite
(dev/tests only) uses plain ``CREATE INDEX``; it supports partial indexes. MySQL
is a no-op: the inventory service runs on PostgreSQL in production, MySQL does
not support partial indexes at all, and an unindexed collection scan on a
dev-sized dataset is acceptable. The models declare the same indexes with
``postgresql_where`` / ``sqlite_where`` only, so a MySQL inventory database
renders them as plain indexes this revision never creates and ``alembic check``
proposes adding all four there. That drift is confined to a dev-only engine.

A concurrent build that fails part-way leaves the index behind marked INVALID,
and the ``IF NOT EXISTS`` above then matches it by name on the retry: the
migration reports success while the planner keeps ignoring the index. Repair it
with ``REINDEX INDEX CONCURRENTLY <name>``, or drop it before re-running.

``schema`` and ``table`` are reserved words, hence the quoted identifiers.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d4f2a7c8b1e6"
down_revision: Union[str, Sequence[str], None] = "e4b8c2f7a915"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RETIRABLE_TABLES = ("node", "service", "schema", "table")
_PARTIAL_WHERE = "retired_at IS NOT NULL"


def _index_name(table_name: str) -> str:
    """Return the partial-index name for a retirable table.

    :param table_name: The retirable table the index covers.
    :return: The index name.
    """
    return f"ix_{table_name}_retired_at_not_null"


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            for table_name in _RETIRABLE_TABLES:
                op.execute(
                    "CREATE INDEX CONCURRENTLY IF NOT EXISTS"
                    f' {_index_name(table_name)} ON "{table_name}" (retired_at)'
                    f" WHERE {_PARTIAL_WHERE}"
                )
    elif dialect == "sqlite":
        for table_name in _RETIRABLE_TABLES:
            op.execute(
                f"CREATE INDEX IF NOT EXISTS {_index_name(table_name)}"
                f' ON "{table_name}" (retired_at) WHERE {_PARTIAL_WHERE}'
            )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            for table_name in _RETIRABLE_TABLES:
                op.execute(
                    f"DROP INDEX CONCURRENTLY IF EXISTS {_index_name(table_name)}"
                )
    elif dialect == "sqlite":
        for table_name in _RETIRABLE_TABLES:
            op.execute(f"DROP INDEX IF EXISTS {_index_name(table_name)}")
