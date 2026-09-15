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

"""add sync health columns to inventory entities

Revision ID: 9f2c14d6b8a7
Revises: 3c39abf7a429
Create Date: 2026-08-31 22:00:00.000000

Add ``last_synced_at``, ``last_sync_error``, ``sync_failing_since`` and
``consecutive_failures`` to the four inventory entities, so a row records how
recently and how successfully the syncer that mirrors it last confirmed it.

The three timestamps and the error text are nullable, which is the correct
reading for a row nothing has reported on yet. ``consecutive_failures`` is NOT
NULL with a ``0`` server default so existing rows land on "not failing" rather
than on an ambiguous NULL; the default is kept rather than dropped, exactly as
``retirement_key``'s is in ``c7d1e94ab3f2``, so a release still running the
previous code can insert without the column.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9f2c14d6b8a7"
down_revision = "3c39abf7a429"
branch_labels = None
depends_on = None

#: Every entity a syncer mirrors, and therefore every table carrying the
#: per-entity sync-health columns.
_SYNCABLE_TABLES = ("node", "service", "schema", "table")

#: The columns added to each table, in the order they are added.
_SYNC_HEALTH_COLUMN_NAMES = (
    "last_synced_at",
    "last_sync_error",
    "sync_failing_since",
    "consecutive_failures",
)


def upgrade() -> None:
    """Add the four sync-health columns to every syncable table.

    The columns are built inline per table rather than hoisted into a shared
    tuple: a ``Column`` binds to the first table it is added to.
    """
    for table_name in _SYNCABLE_TABLES:
        op.add_column(
            table_name,
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("last_sync_error", sa.Text(), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("sync_failing_since", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column(
                "consecutive_failures",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    """Drop the sync-health columns, reversing the order they were added in."""
    for table_name in reversed(_SYNCABLE_TABLES):
        for column_name in reversed(_SYNC_HEALTH_COLUMN_NAMES):
            op.drop_column(table_name, column_name)
