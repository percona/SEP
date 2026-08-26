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

"""add retirement columns to inventory entities

Revision ID: c7d1e94ab3f2
Revises: a38607bba456
Create Date: 2026-08-26 10:30:00.000000

Add ``retired_at`` and ``retirement_key`` to the four inventory entities so an
entity that vanishes upstream can be tombstoned instead of deleted, and rebuild
each unique index to carry ``retirement_key``. Because a unique index treats
NULLs as distinct on every supported dialect, the discriminator is NOT NULL and
defaults to -1 while a row is active; a retired row carries its own primary key
instead, so any number of tombstones may share a key that exactly one active
row can hold.

Downgrade deletes the tombstones before restoring the pre-retirement indexes and
dropping both columns. The deletion is not optional: those indexes constrain
``(external_id, source)`` / ``(port, node_id)`` / ``(name, service_id)`` /
``(name, schema_id)`` alone, so recreating one over a tombstone sharing its key
with an active replacement — the state this revision exists to allow — raises a
duplicate-key error on every dialect. Deleting them restores exactly the
pre-retirement outcome, where the rows would have been hard-deleted instead.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c7d1e94ab3f2"
down_revision = "a38607bba456"
branch_labels = None
depends_on = None

#: Every retirable table, with the unique indexes rebuilt to carry
#: ``retirement_key``: ``(table, index name, pre-retirement columns)``.
_UNIQUE_INDEXES = (
    ("node", "ix_node_external_id_source", ["external_id", "source"]),
    ("service", "ix_service_external_id_node_id", ["external_id", "node_id"]),
    ("service", "ix_service_port_node_id", ["port", "node_id"]),
    ("schema", "ix_schema_name_service_id", ["name", "service_id"]),
    ("table", "ix_table_name_schema_id", ["name", "schema_id"]),
)

_RETIRABLE_TABLES = ("node", "service", "schema", "table")


def upgrade() -> None:
    """Add the retirement columns and rebuild the unique indexes around them."""
    for table_name in _RETIRABLE_TABLES:
        op.add_column(
            table_name,
            sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column(
                "retirement_key",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("-1"),
            ),
        )
    for table_name, index_name, columns in _UNIQUE_INDEXES:
        op.drop_index(index_name, table_name=table_name)
        op.create_index(
            index_name,
            table_name,
            [*columns, "retirement_key"],
            unique=True,
        )


def downgrade() -> None:
    """Delete the tombstones, then restore the unique indexes and drop the columns."""
    for table_name in reversed(_RETIRABLE_TABLES):
        retirable = sa.table(table_name, sa.column("retired_at"))
        op.execute(sa.delete(retirable).where(retirable.c.retired_at.is_not(None)))
    for table_name, index_name, columns in _UNIQUE_INDEXES:
        op.drop_index(index_name, table_name=table_name)
        op.create_index(index_name, table_name, columns, unique=True)
    for table_name in _RETIRABLE_TABLES:
        op.drop_column(table_name, "retirement_key")
        op.drop_column(table_name, "retired_at")
