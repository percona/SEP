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

"""count hosts on a run, not only services

A sweep has attempted hosts as well as services since a host became probeable for its
own sake, but the receipt only ever counted services. That makes a refresh of a
pmm-client host with no database read as "0 of 0 services", which is
indistinguishable from a run that did nothing at all - and that host is precisely the
one OM exists to describe.

Forward-only, rather than editing the migration that created the table: the table is
already applied wherever OM has run, and three nullable-with-default columns are
cheaper than asking anyone to rebuild a database to read a new counter.

Revision ID: e7c4a1b9d3f2
Revises: a3f1c8d24b71
Create Date: 2026-08-18 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.sep.config import sep_settings
from app.sep.om.config import om_schema

# revision identifiers, used by Alembic.
revision: str = "e7c4a1b9d3f2"
down_revision: Union[str, None] = "a3f1c8d24b71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: The counters, each defaulting to zero so existing rows read as "this run predates
#: host counting" rather than as NULL, which every consumer would have to special-case.
_COLUMNS = ("hosts_total", "hosts_probeable", "hosts_answered")


def _schema() -> str | None:
    """Return the real schema OM's tables live in on this bind.

    The model carries a *symbolic* schema translated per bind, so the literal name has
    to be resolved here: SQLite has no schemas at all, and the real-PostgreSQL test
    lane routes every table into a per-worker schema.

    :return: The schema name, or ``None`` when the bind has none.
    """
    return om_schema(sep_settings.DATABASE)


def upgrade() -> None:
    """Add the three host counters."""
    schema = _schema()
    existing = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(
            "inventory_run", schema=schema
        )
    }
    with op.batch_alter_table("inventory_run", schema=schema) as batch_op:
        for name in _COLUMNS:
            if name in existing:
                continue
            batch_op.add_column(
                sa.Column(
                    name, sa.Integer(), nullable=False, server_default=sa.text("0")
                )
            )


def downgrade() -> None:
    """Drop them again."""
    schema = _schema()
    existing = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(
            "inventory_run", schema=schema
        )
    }
    with op.batch_alter_table("inventory_run", schema=schema) as batch_op:
        for name in _COLUMNS:
            if name in existing:
                batch_op.drop_column(name)
