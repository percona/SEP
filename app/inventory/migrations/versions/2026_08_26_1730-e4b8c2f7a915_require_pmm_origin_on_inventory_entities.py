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

"""require pmm origin on inventory entities

Revision ID: e4b8c2f7a915
Revises: c7d1e94ab3f2
Create Date: 2026-08-26 17:30:00.000000

Make ``node.external_id``, ``node.source`` and ``service.external_id`` NOT NULL,
so SEP can no longer hold a node or service PMM never reported.

Rows predating the invariant are classified before the constraints land. They
are retired through the tombstone semantics
:class:`~app.inventory.crud.RetirableManagerMixin` uses — ``retired_at`` plus
``retirement_key = id``, cascading deepest-first — rather than deleted, so the
references SEP persisted to them keep resolving. Retirement alone does not
satisfy a NOT NULL constraint, so the classified rows are then stamped with a
synthetic origin: ``source = 'PMM'`` and, where no real identifier exists, an
``external_id`` of ``sep-legacy:<pk>``. Every stamped row is retired, and
retired rows are excluded from active reads by default, so the fabricated origin
is confined to tombstones and its provenance stays legible on an
``include_retired=true`` read. Reviving such a tombstone yields a live node with
a fabricated origin; that is an accepted limitation, since rejecting it would
require application code to recognise the ``sep-legacy:`` prefix.

Every statement is built through SQLAlchemy Core rather than spelled as raw SQL,
because all three supported engines are reachable here and each step diverges on
at least one of them: ``schema``'s child table is named ``table``, a reserved
word MySQL quotes with backticks and the others with double quotes; string
concatenation is ``||`` on SQLite and PostgreSQL but ``CONCAT()`` on MySQL,
where ``||`` is boolean OR under the default SQL mode; and ``CAST`` targets
``VARCHAR`` on SQLite and PostgreSQL but ``CHAR`` on MySQL. The source label is
the one deliberate exception, kept as an inline literal so PostgreSQL coerces it
to ``sourceenum`` — asyncpg sends a bound parameter as typed text, which it
refuses to assign to an enum column.

Downgrade restores nullability and touches no data. Stripping the synthetic
identifiers by matching the ``sep-legacy:`` prefix would treat it as a reserved
namespace, and nothing reserves it: ``external_id`` is unconstrained, so a
genuine upstream identifier matching the pattern would be nulled and its row
misclassified on any later re-upgrade. Leaving the data alone is also sound
rather than merely cheaper — the stamped rows are all retired and therefore
absent from active reads, and a re-upgrade finds no NULLs to classify. A
fabricated ``source`` is in any case indistinguishable from a genuine one once
written, so no downgrade could recover it.
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

from app.core.utils.date_time import utc_now

# revision identifiers, used by Alembic.
revision = "e4b8c2f7a915"
down_revision = "c7d1e94ab3f2"
branch_labels = None
depends_on = None

#: Prefix marking an ``external_id`` fabricated by this revision.
_LEGACY_PREFIX = "sep-legacy:"

#: ``sa.Enum(SourceEnum)`` persists the member *name*, so the stored label is
#: uppercase ``PMM`` even though ``SourceEnum.PMM.value`` is lowercase.
_SOURCE_LABEL = "PMM"

def _retirable(name: str, *columns: sa.ColumnClause) -> sa.TableClause:
    """Build a lightweight table clause carrying the retirement columns.

    The columns are constructed per call because a SQLAlchemy column object
    belongs to exactly one table and cannot be shared across these four.

    :param name: The table's name.
    :param columns: The table's own columns, beyond ``id`` and the retirement pair.
    :return: The table clause.
    """
    return sa.table(
        name,
        sa.column("id", sa.Integer()),
        *columns,
        sa.column("retired_at", sa.DateTime(timezone=True)),
        sa.column("retirement_key", sa.Integer()),
    )


_NODE = _retirable(
    "node",
    sa.column("external_id", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("source", sa.Enum(_SOURCE_LABEL, name="sourceenum")),
)
_SERVICE = _retirable(
    "service",
    sa.column("external_id", sqlmodel.sql.sqltypes.AutoString()),
    sa.column("node_id", sa.Integer()),
)
_SCHEMA = _retirable("schema", sa.column("service_id", sa.Integer()))
_TABLE = _retirable("table", sa.column("schema_id", sa.Integer()))

_ORIGIN_LESS_NODES = sa.select(_NODE.c.id).where(
    sa.or_(_NODE.c.external_id.is_(None), _NODE.c.source.is_(None))
)
_DOOMED_SERVICES = sa.select(_SERVICE.c.id).where(
    sa.or_(
        _SERVICE.c.external_id.is_(None),
        _SERVICE.c.node_id.in_(_ORIGIN_LESS_NODES),
    )
)
_DOOMED_SCHEMAS = sa.select(_SCHEMA.c.id).where(
    _SCHEMA.c.service_id.in_(_DOOMED_SERVICES)
)

#: The tombstone cascade, deepest first, so a torn write can only ever leave
#: retired descendants under an active ancestor.
_RETIREMENT_CASCADE = (
    (_TABLE, _TABLE.c.schema_id.in_(_DOOMED_SCHEMAS)),
    (_SCHEMA, _SCHEMA.c.service_id.in_(_DOOMED_SERVICES)),
    (_SERVICE, _SERVICE.c.id.in_(_DOOMED_SERVICES)),
    (_NODE, _NODE.c.id.in_(_ORIGIN_LESS_NODES)),
)

#: ``(table, column, type)`` for each column the constraints land on. The types
#: are the ones the create-tables revision used, so MySQL's ``MODIFY COLUMN``
#: restates the column faithfully instead of rejecting an unbounded ``VARCHAR``.
_MANDATORY_COLUMNS = (
    ("node", "external_id", sqlmodel.sql.sqltypes.AutoString()),
    ("node", "source", sa.Enum(_SOURCE_LABEL, name="sourceenum")),
    ("service", "external_id", sqlmodel.sql.sqltypes.AutoString()),
)


def _legacy_external_id(table: sa.TableClause) -> sa.ColumnElement:
    """Build the synthetic ``external_id`` expression for one table.

    :param table: The table whose primary key seeds the identifier.
    :return: ``'sep-legacy:' || <pk>``, rendered per the target dialect.
    """
    return sa.literal(_LEGACY_PREFIX).concat(sa.cast(table.c.id, sa.String()))


def upgrade() -> None:
    """Retire origin-less rows, stamp a synthetic origin, then constrain."""
    retired_at = utc_now()
    for table, predicate in _RETIREMENT_CASCADE:
        # ``retired_at IS NULL`` leaves an existing tombstone's original
        # timestamp alone, mirroring ``RetirableManagerMixin._retire``.
        op.execute(
            sa.update(table)
            .where(table.c.retired_at.is_(None), predicate)
            .values(retired_at=retired_at, retirement_key=table.c.id)
        )
    # Keyed on NULL-ness, not on what the cascade above retired: a row retired
    # earlier through DELETE /nodes/{id} still holds NULLs and still blocks the
    # constraint.
    op.execute(
        sa.update(_NODE)
        .where(sa.or_(_NODE.c.external_id.is_(None), _NODE.c.source.is_(None)))
        .values(
            external_id=sa.func.coalesce(
                _NODE.c.external_id, _legacy_external_id(_NODE)
            ),
            source=sa.literal_column(f"'{_SOURCE_LABEL}'"),
        )
    )
    op.execute(
        sa.update(_SERVICE)
        .where(_SERVICE.c.external_id.is_(None))
        .values(external_id=_legacy_external_id(_SERVICE))
    )
    # Batch mode is required, not stylistic: SQLite has no
    # ALTER COLUMN ... SET NOT NULL. On PostgreSQL it emits a plain ALTER.
    for table_name, column, type_ in _MANDATORY_COLUMNS:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(column, existing_type=type_, nullable=False)


def downgrade() -> None:
    """Restore nullability on the three columns, leaving every row untouched."""
    for table_name, column, type_ in reversed(_MANDATORY_COLUMNS):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(column, existing_type=type_, nullable=True)
