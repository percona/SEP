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

"""rename app periodic task table

Revision ID: 93cf1ec26fcd
Revises: ee2b220c8c73
Create Date: 2026-09-24 13:00:00.000000

Move the table that maps an app-owned Celery schedule to its owning app from
``seppluginperiodictask`` to ``extensionsappperiodictask``, the name its model
class ``ExtensionsAppPeriodicTask`` now derives. Its two indexes follow, and on
PostgreSQL so do the primary-key constraint and the id sequence, which carry the
table name too.

The rows it holds name their schedules by the beat ``PeriodicTask.name``, and
the prefix those names are seeded under moves from ``sep__`` to
``extensions__`` in the same release. Startup seeding deletes every wrapper row
whose name it no longer seeds, so a row left under the old prefix would be
replaced, and the operator's ``user_enabled`` choice on it lost. The rows are
renamed in place instead.

A syncer is stored by its dotted class path, which named the package too, in the
sync run and entity-absence tables. Those move with it, so a syncer keeps its
run history and its absence counts across the upgrade.

The track's main branch takes the ``extensions_main`` label here. Its first
label, ``sep_main``, is history and stays on the revision that set it; the
Makefile and tests address the branch through the new one.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "93cf1ec26fcd"
down_revision = "ee2b220c8c73"
branch_labels = ("extensions_main",)
depends_on = None

_OLD_TABLE = "seppluginperiodictask"
_NEW_TABLE = "extensionsappperiodictask"
_INDEXED_COLUMNS = (("app_key", False), ("periodic_task_name", True))
_OLD_NAME_PREFIX = "sep__"
_NEW_NAME_PREFIX = "extensions__"
_SYNCER_TABLES = ("syncinstance", "syncentityabsence")
_OLD_SYNCER_PREFIX = "app.sep."
_NEW_SYNCER_PREFIX = "app.extensions."


def _rename_table(source: str, target: str) -> None:
    """Rename the table with its indexes, and on PostgreSQL its key and sequence.

    :param source: The table's current name.
    :param target: The name to give it.
    """
    op.rename_table(source, target)
    for column, unique in _INDEXED_COLUMNS:
        op.drop_index(f"ix_{source}_{column}", table_name=target)
        op.create_index(f"ix_{target}_{column}", target, [column], unique=unique)
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            f"ALTER TABLE {target} RENAME CONSTRAINT {source}_pkey TO {target}_pkey"
        )
        op.execute(f"ALTER SEQUENCE {source}_id_seq RENAME TO {target}_id_seq")


def _rename_prefix(table: str, column: str, source: str, target: str) -> None:
    """Move every stored value of one column from one prefix to the other.

    :param table: The table holding the values.
    :param column: The column holding the values.
    :param source: The prefix the values carry.
    :param target: The prefix to store instead.
    """
    values = sa.column(column, sa.String)
    op.execute(
        sa.update(sa.table(table, values))
        .where(sa.func.substr(values, 1, len(source)) == source)
        .values(
            {
                column: sa.literal(target, sa.String).concat(
                    sa.func.substr(values, len(source) + 1)
                )
            }
        )
    )


def upgrade() -> None:
    """Rename the table and move its schedule names and the stored syncers."""
    _rename_table(_OLD_TABLE, _NEW_TABLE)
    _rename_prefix(_NEW_TABLE, "periodic_task_name", _OLD_NAME_PREFIX, _NEW_NAME_PREFIX)
    for table in _SYNCER_TABLES:
        _rename_prefix(table, "syncer", _OLD_SYNCER_PREFIX, _NEW_SYNCER_PREFIX)


def downgrade() -> None:
    """Restore the table name and the prefixes the earlier revisions expect."""
    for table in _SYNCER_TABLES:
        _rename_prefix(table, "syncer", _NEW_SYNCER_PREFIX, _OLD_SYNCER_PREFIX)
    _rename_prefix(_NEW_TABLE, "periodic_task_name", _NEW_NAME_PREFIX, _OLD_NAME_PREFIX)
    _rename_table(_NEW_TABLE, _OLD_TABLE)
