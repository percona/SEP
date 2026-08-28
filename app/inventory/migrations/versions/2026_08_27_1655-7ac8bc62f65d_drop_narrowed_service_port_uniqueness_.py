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

"""drop narrowed service port uniqueness index

Revision ID: 7ac8bc62f65d
Revises: e4b8c2f7a915
Create Date: 2026-08-27 16:55:03.926346

``service.external_id`` is NOT NULL as of e4b8c2f7a915, so every row now carries
an external identity. ``ix_service_port_node_id`` constrained ``(port, node_id,
retirement_key)`` for every row regardless of identity, which rejected the
legitimate case of several databases behind one PostgreSQL or MySQL server
sharing that server's port and being registered as separate services. Dropping
it outright is the honest version of narrowing it to a NULL-able discriminator:
that approach relied on an externally identified row carrying a NULL guard
(unique indexes treat NULLs as distinct), and since every row is externally
identified now, the guard would be NULL for all of them and the constraint
would already be inert for everyone.

Downgrade deletes the extra same-port services before restoring the index —
see its own docstring for why. It also has to leave the index in place for
c7d1e94ab3f2's downgrade, several steps further back in the chain: that
revision unconditionally drops and recreates ``ix_service_port_node_id`` as
part of restoring the pre-retirement-key indexes, so a downgrade chain running
through both revisions needs the index to exist by the time it gets there.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "7ac8bc62f65d"
down_revision = "e4b8c2f7a915"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop the port-uniqueness index; several services may now share a port."""
    op.drop_index("ix_service_port_node_id", table_name="service")


def downgrade() -> None:
    """Delete the extra same-port services, then restore the dropped index.

    The deletion is not optional: the restored index constrains ``(port,
    node_id, retirement_key)``, so re-creating it over the same-port pairs this
    revision exists to allow raises a duplicate-key error on every dialect.
    Keeping the lowest-id row of each group restores the pre-fix outcome, where
    the second service was never created at all.

    The ``port IS NOT NULL`` filter appears in both the subquery and the delete
    because SQL ``GROUP BY`` treats NULLs as equal, which would otherwise
    collapse every port-less service into one group the dropped index never
    constrained. The ``.subquery()`` wrapper is what makes the statement legal
    on MySQL, which rejects a DELETE whose subquery names the target table.
    """
    service = sa.table(
        "service",
        sa.column("id"),
        sa.column("port"),
        sa.column("node_id"),
        sa.column("retirement_key"),
    )
    survivors = (
        sa.select(sa.func.min(service.c.id).label("id"))
        .where(service.c.port.is_not(None))
        .group_by(service.c.port, service.c.node_id, service.c.retirement_key)
        .subquery()
    )
    op.execute(
        sa.delete(service).where(
            service.c.port.is_not(None),
            service.c.id.not_in(sa.select(survivors.c.id)),
        )
    )
    op.create_index(
        "ix_service_port_node_id",
        "service",
        ["port", "node_id", "retirement_key"],
        unique=True,
    )
