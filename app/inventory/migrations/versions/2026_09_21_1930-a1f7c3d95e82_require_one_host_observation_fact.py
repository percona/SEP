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

"""require one host observation fact

Revision ID: a1f7c3d95e82
Revises: b351dd0aaed8
Create Date: 2026-09-21 19:30:00.000000

Give ``hostsystemobservation`` a table-level guard for the invariant only
``HostSystemObservationWrite``'s validator held: at least one of ``os_version``,
``installed_packages``, ``config`` and ``can_elevate`` must be non-NULL.

Rows that would violate the CHECK are deleted first, unconditionally, following
the remediate-in-migration principle ``e4b8c2f7a915`` established for
``node.external_id`` / ``service.external_id``: SEP ships as an
independently-deployed sidecar per customer, so there is no fleet-wide database
an audit could clear on every installation's behalf, and a constraint that
aborts somebody's upgrade is not a constraint that ships. It remediates by
deleting rather than by retiring and backfilling, because an absent observed
fact cannot be synthesized the way an identifier can. At the API layer the
deleted row is indistinguishable from the "never observed" case
``get_host_system_observation`` already answers with a 404, so removing it
corrects the response rather than degrading it; what is lost is the
``observed_at`` of a collection that returned nothing, which is why every
deleted row is logged at WARNING first. Nothing in a released SEP creates such a
row — the validator and the table landed together, and the sole producer returns
``None`` when no fact was collected — so this step is a pre-flight for rows
introduced by hand-written SQL, a restored backup or a future bug.

Both steps go through SQLAlchemy Core rather than raw SQL, for the reasons
``e4b8c2f7a915``'s docstring spells out: all three supported engines are
reachable here and their spellings diverge. The CHECK is added inside
``batch_alter_table`` because SQLite has no ``ALTER TABLE ... ADD CONSTRAINT``;
batch mode recreates the table there and emits a plain ``ALTER`` elsewhere.

Downgrade drops the CHECK and restores nothing. Unlike ``e4b8c2f7a915``, whose
upgrade only retired and backfilled, this one genuinely discards rows — an
all-NULL observation carries no fact worth restoring.
"""

import logging

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1f7c3d95e82"
down_revision = "b351dd0aaed8"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)

_TABLE_NAME = "hostsystemobservation"

#: Spelled out rather than imported from ``HostSystemObservation.__table_args__``,
#: so this revision keeps creating the CHECK it was written to create even after a
#: later field joins ``HOST_OBSERVATION_FIELD_NAMES``. The model declares the same
#: name, which is what lets ``downgrade()`` drop the constraint it created.
_CONSTRAINT_NAME = "ck_hostsystemobservation_at_least_one_fact"

#: The fact columns the CHECK covers, plus the two that identify and date the
#: row so a deletion can be reported before it happens.
_OBSERVATION = sa.table(
    _TABLE_NAME,
    sa.column("id", sa.Integer()),
    sa.column("node_id", sa.Integer()),
    sa.column("observed_at", sa.DateTime(timezone=True)),
    sa.column("os_version", sa.String()),
    sa.column("installed_packages", sa.JSON()),
    sa.column("config", sa.JSON()),
    sa.column("can_elevate", sa.Boolean()),
)

_FACT_COLUMNS = (
    _OBSERVATION.c.os_version,
    _OBSERVATION.c.installed_packages,
    _OBSERVATION.c.config,
    _OBSERVATION.c.can_elevate,
)

_HAS_NO_FACT = sa.and_(*(fact.is_(None) for fact in _FACT_COLUMNS))
_HAS_A_FACT = sa.or_(*(sa.column(fact.name).is_not(None) for fact in _FACT_COLUMNS))


def upgrade() -> None:
    """Delete fact-less observations, then constrain the table against new ones."""
    bind = op.get_bind()
    factless = bind.execute(
        sa.select(_OBSERVATION.c.node_id, _OBSERVATION.c.observed_at).where(
            _HAS_NO_FACT
        )
    ).all()
    if factless:
        logger.warning(
            "Deleting %s hostsystemobservation row(s) holding no observed fact; "
            "the API already reports such a node as never observed.",
            len(factless),
        )
        for node_id, observed_at in factless:
            logger.warning(
                "Deleting fact-less hostsystemobservation for node_id=%s "
                "observed_at=%s.",
                node_id,
                observed_at,
            )
        bind.execute(sa.delete(_OBSERVATION).where(_HAS_NO_FACT))
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.create_check_constraint(_CONSTRAINT_NAME, _HAS_A_FACT)


def downgrade() -> None:
    """Drop the CHECK, leaving the rows ``upgrade()`` deleted gone."""
    with op.batch_alter_table(_TABLE_NAME) as batch_op:
        batch_op.drop_constraint(_CONSTRAINT_NAME, type_="check")
