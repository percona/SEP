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

"""add taskhistory_log stream end_offset index

Revision ID: e3d856712405
Revises: fa5b80a1c8e0
Create Date: 2026-06-30 18:39:03.071686

Add a composite index on ``taskhistory_log (task_history_id, source, stream,
end_offset)`` so the rolling per-stream byte cap's bounded eviction delete can
locate the oldest chunks (``end_offset <= low_water`` filtered by the
``(task_history_id, source, stream)`` triple, ordered by ``end_offset``) with an
index scan instead of a sequential scan. The existing ``uq_taskhistory_log_chunk``
unique index is keyed on ``start_offset``, so it does not serve this query.

PostgreSQL builds the index with ``CREATE INDEX CONCURRENTLY`` inside an
autocommit block so creation does not block concurrent log writes on an already
large ``taskhistory_log`` table; ``CONCURRENTLY`` cannot run inside a
transaction, which is why the ``autocommit_block`` is required. SQLite and dev
MySQL use a plain ``CREATE INDEX`` over plain columns (no expression cast, so no
MySQL no-op is needed).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e3d856712405"
down_revision: Union[str, None] = "fa5b80a1c8e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "ix_taskhistory_log_stream_end_offset"
_TABLE_NAME = "taskhistory_log"
_COLUMNS = ("task_history_id", "source", "stream", "end_offset")


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} "
                f"ON {_TABLE_NAME} ({', '.join(_COLUMNS)})"
            )
    else:
        op.create_index(_INDEX_NAME, _TABLE_NAME, list(_COLUMNS))


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
    else:
        op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
