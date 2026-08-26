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

"""narrow service port uniqueness to unidentified services

Revision ID: 91c704d3a08a
Revises: c7d1e94ab3f2
Create Date: 2026-08-26 18:48:26.402784

Add ``port_guard_key`` to ``service`` and rebuild ``ix_service_port_node_id``
around it, so the port key binds only the services their upstream source does
not identify. Several databases behind one PostgreSQL or MySQL server share
that server's port and are registered as separate services, so ``(port,
node_id)`` was rejecting rows that are legitimately distinct.

The guard is NULL on a row carrying an ``external_id`` and -1 otherwise. A
unique index treats NULLs as distinct on every supported dialect, so an
identified row never collides; -1 is truthy, which is what keeps the Python
duplicate check in ``BaseSQLModelManager.save`` running for the rows the index
still protects.

Downgrade deletes the extra same-port services before restoring the
pre-narrowing index, for the reason its own docstring gives.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "91c704d3a08a"
down_revision = "c7d1e94ab3f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the port guard and confine the port index to unidentified services.

    The column carries a server default of -1 even though the application always
    sets it explicitly: between this revision running and the new code going
    live, an old process inserting a service omits the column, and a NULL there
    would leave the row unconstrained by the very index meant to protect it.
    Defaulting to the sentinel keeps such a row conservatively constrained,
    which is exactly the pre-narrowing behaviour. The UPDATE then clears the
    guard on the rows that do carry an external identity.
    """
    op.add_column(
        "service",
        sa.Column(
            "port_guard_key",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("-1"),
        ),
    )
    service = sa.table("service", sa.column("external_id"), sa.column("port_guard_key"))
    op.execute(
        sa.update(service)
        .where(service.c.external_id.is_not(None))
        .values(port_guard_key=None)
    )
    op.drop_index("ix_service_port_node_id", table_name="service")
    op.create_index(
        "ix_service_port_node_id",
        "service",
        ["port", "node_id", "retirement_key", "port_guard_key"],
        unique=True,
    )


def downgrade() -> None:
    """Drop the extra same-port services, then restore the pre-narrowing index.

    The deletion is not optional: the restored index constrains ``(port,
    node_id, retirement_key)`` alone, so re-creating it over the two active
    same-port services this revision exists to allow raises a duplicate-key
    error on every dialect. Keeping the lowest-id row of each group restores the
    pre-narrowing outcome, where the second service was never created at all.

    The ``port IS NOT NULL`` filter appears in both the subquery and the delete
    because SQL ``GROUP BY`` treats NULLs as equal, which would otherwise
    collapse every port-less service into one group the old index never
    constrained. The ``.subquery()`` wrapper is what makes the statement legal
    on MySQL, which rejects a DELETE whose subquery names the target table.
    """
    service = sa.table(
        "service",
        sa.column("id"),
        sa.column("port"),
        sa.column("node_id"),
        sa.column("retirement_key"),
        sa.column("port_guard_key"),
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
    op.drop_index("ix_service_port_node_id", table_name="service")
    op.create_index(
        "ix_service_port_node_id",
        "service",
        ["port", "node_id", "retirement_key"],
        unique=True,
    )
    op.drop_column("service", "port_guard_key")
