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

"""Define the OpenManager Inventory persistence models.

Three tables, and the split between them is the design:

``om.host`` and ``om.service``
    What the estate *is*, one row per entity, upserted. A host row exists whether or
    not any MongoDB was found on it, which is what makes "which pmm-clients have no
    database" answerable at all -- and it is not hypothetical: the sandbox carries
    hosts with a PMM client and nothing else beside arbiters running a mongod PMM has
    no service for, and PMM's inventory describes the two identically.

``om.inventory_run``
    What one sweep *did*. A receipt, not a copy of the estate: which entity was
    attempted, on which executor host, whether it answered, and any error. Keeping
    the collected attributes out of it is load-bearing -- with ``RUN_RETENTION``
    runs kept, putting them here stores the same facts that many times over, and
    creates a second source of truth for them.

Each entity carries a few real columns for identity and freshness plus one JSONB
document of everything probed, so changing what is collected is a payload change
rather than a migration. The cost is that fleet-wide questions become JSONB queries;
promoting a field to a column later is easy and the reverse is not.

This module is loaded by Alembic through ``spec_from_file_location`` without running
the package ``__init__``, so it must not import sibling app modules. That is also why
the schema below is a bare string rather than
``app.sep.om.config.OM_SCHEMA_SYMBOL``: the token has to be spelled here, and
``sqlalchemy_celery_beat`` makes the same trade with ``celery_schema``.
"""

from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Column, ForeignKey, Index, JSON, Text, text
from sqlalchemy import Enum as EnumField
from sqlalchemy.dialects import postgresql
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from app.core.db.models import BaseUUIDSQLModel, DateTimeWithTimezone
from app.core.utils.date_time import utc_now
from app.core.utils.fields import UTCDatetime

#: The symbolic schema every table here declares. See the module docstring for why it
#: is spelled rather than imported.
OM_SCHEMA = "om_schema"

# Table names are short -- ``host``, ``service``, ``inventory_run`` -- because the
# schema is what qualifies them. ``om.service`` is a different table from SEP
# inventory's ``service``, and in production nothing has to arrange that: on
# PostgreSQL the schema separates them, and on SQLite the two services keep separate
# database files. The one place they *would* collide is the test suite, which creates
# every service's metadata in a single in-memory database -- so the root conftest
# gives each SQLite connection a real ``om`` schema with ``ATTACH`` rather than
# letting the token fall back to the default one.


def _observed_document_type() -> Any:
    """Build the column type for an ``observed`` document.

    A fresh type instance per call. A single shared ``Column`` cannot be reused across
    two models -- SQLAlchemy binds a Column to exactly one Table -- which is why the
    freshness mixin below declares types rather than columns.

    :return: ``JSONB`` on PostgreSQL, ``JSON`` elsewhere.
    """
    return postgresql.JSONB(astext_type=Text()).with_variant(JSON(), "sqlite")


class ProbeRunStatus(StrEnum):
    """Enumerate the states of one probe sweep.

    ``PARTIAL`` is the common steady state, not an alarm: the probe reaches only
    services whose node runs a healthy ``raw_exec`` executor, and an inventory row
    routinely outlives the executor that served it.

    :cvar RUNNING: The sweep is in flight.
    :cvar SUCCESS: Every service that resolved to a live executor answered.
    :cvar PARTIAL: Some answered, some did not.
    :cvar FAILED: None answered, or the sweep raised.
    :cvar SKIPPED: Refused before doing any work, because another sweep already held
        the hosts it would have covered. Recorded rather than skipped silently: a
        scheduled sweep that quietly does nothing leaves a ten-minute gap in the
        history that reads exactly like the schedule having fired and found nothing.
    """

    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class NodeResolution(StrEnum):
    """Enumerate how a service was mapped to an executor host.

    ``ORPHANED`` is a first-class outcome, not an error: an inventory row routinely
    outlives the executor that served it, and recording it is what keeps a sweep from
    probing the wrong host and reporting confidently wrong facts about it.

    :cvar NAME: Matched an executor host by node name.
    :cvar ADDRESS: Matched an executor host by node address.
    :cvar ORPHANED: No live executor host serves this service.
    """

    NAME = "name"
    ADDRESS = "address"
    ORPHANED = "orphaned"


class ObservedEntity(SQLModel):
    """Carry the columns every probed entity has, whatever it is.

    Not a table: a mixin, so the two entity tables cannot drift apart on
    the freshness rules. Each field declares a *type* rather than a ``Column``,
    because a Column instance binds to exactly one Table and sharing one across two
    models fails at import.

    The lifecycle these implement is four rules, each cheap now and expensive to
    discover later:

    * ``failing_since`` is set with ``COALESCE(failing_since, now())`` -- overwrite it
      on every failure and "since" quietly becomes "most recent failure", so the
      duration is always about one schedule interval and the column is worthless;
    * a failed probe must **not** erase ``observed``. The last known good document is
      kept with its own ``collected_at``, because what a host was running when last
      seen is exactly what is wanted while it is unreachable;
    * only a run that actually attempted an entity touches its timestamps, so a
      single-host refresh does not mark everything it skipped as failed;
    * the upsert lists the columns it owns explicitly. Nothing here is user-writable
      *yet*, so there is nothing to clobber -- but a blanket ``ON CONFLICT DO UPDATE``
      over every column wipes the first field that ever is.

    :param observed: Everything the probe collected, with its own ``collected_at``.
        Non-nullable with a ``{}`` default rather than nullable: SEP's ``AutoJSON``
        stores a Python ``None`` as the JSON scalar ``null``, so "never probed" and
        "probed, found nothing" would be indistinguishable.
    :param first_seen_at: When OM first wrote a row for this entity.
    :param last_attempt_at: When a run last targeted it. Not "when a run last ran".
    :param last_success_at: When it last answered. This is the data's age.
    :param failing_since: The **first** failure after the last success, so the column
        says "failing for three days" rather than "failed a minute ago". ``None``
        while healthy.
    :param consecutive_failures: Failures since the last success.
    :param last_error: The most recent failure detail.
    :param last_run_id: The run that last attempted it, for joining to the receipt.
    :param updated_at: When this row last changed.
    """

    observed: dict[str, Any] = SQLField(
        default_factory=dict,
        sa_type=_observed_document_type(),
        nullable=False,
        sa_column_kwargs={"server_default": "{}"},
    )
    first_seen_at: UTCDatetime = SQLField(
        default_factory=utc_now, sa_type=DateTimeWithTimezone, nullable=False
    )
    last_attempt_at: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )
    last_success_at: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )
    failing_since: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )
    consecutive_failures: int = SQLField(default=0, nullable=False)
    last_error: str | None = SQLField(default=None)
    last_run_id: UUID | None = SQLField(default=None)
    updated_at: UTCDatetime = SQLField(
        default_factory=utc_now, sa_type=DateTimeWithTimezone, nullable=False
    )


class OmHost(ObservedEntity, table=True):
    """Record one host, whether or not a database was found on it.

    Keyed on **PMM's** node id. OM is not the system of record for identity here,
    PMM is, so the table and the API speak the id every consumer already holds and
    nothing needs translating anywhere -- including the scoped refresh, which takes
    the ``node_id`` PMM already has.

    ``text``, not ``uuid``: PMM's ids are usually UUIDs but not always. The PMM
    server's own node is the literal string ``pmm-server`` in every deployment, and a
    ``uuid`` column would reject the one node every installation has.

    The consequence to accept openly is that if PMM re-registers a node under a new
    id, OM gets a second row and the old one stays until retention prunes it. The
    usual answer -- a OM-minted id plus a natural key to recognise the machine across
    ids -- has no natural key available: ``machine_id`` is inherited from the container
    image, so most of this sandbox reports one shared value and the rest report an
    empty string. Matching on it would merge unrelated hosts. Hence no surrogate key:
    it would only move the guess into a matching function.

    Class named ``OmHost`` rather than ``Host`` even though the *table* is
    ``om.host``: the schema qualifies the table, but SQLModel keeps one registry for
    the whole application and it already carries ``app.inventory.models.Service``, so
    the short class names are genuinely taken. The pair is kept symmetrical.

    :param node_id: PMM's node id, the primary key.
    :param name: The node's registered name.
    :param address: The node's registered address.
    :param executor_host: The Nomad client that serves it, ``None`` when none does.
    """

    __tablename__ = "host"
    __table_args__ = (
        # Partial: the healthy majority is not in the index at all. Expressed here
        # rather than with ``index=True`` because a ``WHERE`` clause cannot be, and
        # OM's migrations are hand-written anyway (autogenerate is off for them).
        Index(
            "ix_om_host_failing_since",
            "failing_since",
            postgresql_where=text("failing_since IS NOT NULL"),
        ),
        {"schema": OM_SCHEMA},
    )

    node_id: str = SQLField(sa_type=Text, primary_key=True)
    name: str = SQLField(sa_type=Text, nullable=False)
    address: str | None = SQLField(default=None, sa_type=Text)
    executor_host: str | None = SQLField(default=None, sa_type=Text)


class OmService(ObservedEntity, table=True):
    """Record one MongoDB service PMM has registered, on its host.

    A service row is a service **PMM knows** -- that is what keying on ``service_id``
    means. The probe will still find mongod processes PMM has no service for, and
    those are recorded on the host's ``observed`` document instead: no identity to
    invent, no schema commitment, and the estate view does not get to claim the host
    is empty when it is not. Arbiters are the reason that case is normal rather than
    exotic: one holds no data, therefore no user documents, therefore SCRAM cannot
    authenticate, therefore ``pmm-admin add mongodb`` fails for it.

    The foreign key is safe because both tables belong to *this* app. Across apps the
    ``om`` schema takes no foreign keys at all: each app that owns migrations is an
    independent branch, an image that strips an app removes its ``versions/``
    directory, and there is no guaranteed ordering between branches -- so an FK into
    another app's table can reference something that legitimately vanishes.

    :param service_id: PMM's service id, the primary key. ``text`` for the same
        reason as :attr:`OmHost.node_id`.
    :param node_id: The host it runs on.
    :param name: The service name as PMM registered it.
    :param port: The port it listens on.
    :param role: What the probe found it to be -- ``mongod``, ``mongos``, ``config``,
        ``arbiter``. Observed, not declared: plain text rather than an enum, because a
        role we have not thought of should land in the column rather than raise. (An
        enum would also need care: SQLAlchemy's non-native ``Enum`` persists by member
        *name*, so a CHECK constraint listing lowercase values rejects every insert.)
    """

    __tablename__ = "service"
    __table_args__ = (
        # Named rather than left to ``index=True``, which derives the name from the
        # *declared* table -- and the declared schema is the symbolic token, so the
        # index would ship into the real ``om`` schema called
        # ``ix_om_schema_service_node_id``.
        Index("ix_om_service_node_id", "node_id"),
        {"schema": OM_SCHEMA},
    )

    service_id: str = SQLField(sa_type=Text, primary_key=True)
    node_id: str = SQLField(
        sa_column=Column(
            Text,
            # Qualified with the symbolic schema: the FK target is resolved against
            # the *declared* name, and the connection translates both sides together.
            ForeignKey(f"{OM_SCHEMA}.host.node_id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    name: str | None = SQLField(default=None, sa_type=Text)
    port: int | None = SQLField(default=None)
    role: str | None = SQLField(default=None, sa_type=Text)


class ProbeRun(BaseUUIDSQLModel, table=True):
    """Record one probe sweep and the facts it collected.

    :param started_at: When the sweep began.
    :param finished_at: When it reached a terminal status; ``None`` while running.
    :param status: The sweep's lifecycle state.
    :param services_total: MongoDB services inventory reported.
    :param services_resolved: ...of which mapped to a live executor host.
    :param services_orphaned: ...of which did not. Not an error.
    :param services_answered: Services that returned a usable probe record.
    :param hosts_total: Hosts in scope this sweep, service or no service.
    :param hosts_probeable: ...of which had a usable executor to dispatch to. The
        difference from ``hosts_total`` is the estate nothing can be run on, which is
        a fact about onboarding rather than a failure of the sweep.
    :param hosts_answered: Hosts that returned a usable record.
    :param facts: The collected facts, each ``{service_id, field, value,
        observed_at}`` where ``service_id`` is **PMM's** service UUID -- the only key
        the consumer can join on, and the reason the API translates away SEP's own
        inventory id before storing.
    :param nodes: One record per mapped service: where it was probed, how that host
        was matched, whether it answered and how long its host took. The counters
        above are this list's summary, and a summary is all a sweep could show until
        this column existed -- "5 of 14 answered" cannot say *which* five, on which
        hosts, or which one took a minute.
    :param scope: The node ids this run was asked to refresh, or ``None`` for the
        whole estate. Stored rather than inferred, because without it the receipt
        cannot be read honestly -- "9 of 13 answered" means something different when
        the run was only ever asked about one host -- and because the single-flight
        guard has nothing to compare against.
    :param error: The failure detail when the sweep itself raised.
    """

    __tablename__ = "inventory_run"
    # A *symbolic* schema, translated per bind by the engine
    # (``app/sep/om/config.py``). Never a literal: SQLite has no schemas, so a real
    # name here would make the table uncreatable in the unit suite, and the
    # real-PostgreSQL lane routes every table into a per-xdist-worker schema that a
    # hard-coded ``om`` would escape and then collide across workers.
    __table_args__ = {"schema": "om_schema"}

    started_at: UTCDatetime = SQLField(
        sa_type=DateTimeWithTimezone, default_factory=utc_now, index=True
    )
    finished_at: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )
    status: ProbeRunStatus = SQLField(
        default=ProbeRunStatus.RUNNING,
        sa_column=Column(
            EnumField(ProbeRunStatus, native_enum=False, create_constraint=True),
            nullable=False,
            index=True,
        ),
    )

    services_total: int = SQLField(default=0)
    services_resolved: int = SQLField(default=0)
    services_orphaned: int = SQLField(default=0)
    services_answered: int = SQLField(default=0)

    # A sweep attempts hosts as well as services, and has since a host became
    # probeable for its own sake. Counting only services made a refresh of a
    # pmm-client host with no database read as "0 of 0", which is indistinguishable
    # from a run that did nothing.
    hosts_total: int = SQLField(default=0)
    hosts_probeable: int = SQLField(default=0)
    hosts_answered: int = SQLField(default=0)

    # Explicit JSONB rather than ``AutoJSON``: the latter silently drops
    # ``none_as_null`` on PostgreSQL, so a Python ``None`` lands as the JSON scalar
    # ``null`` and a caller cannot tell "no facts" from "the column was never set".
    facts: list[dict[str, Any]] = SQLField(
        default_factory=list,
        sa_column=Column(
            postgresql.JSONB(astext_type=JSON()).with_variant(JSON(), "sqlite"),
            nullable=False,
            server_default="[]",
        ),
    )
    # Same JSONB treatment, and for the same reason: a run reads its nodes all at
    # once or not at all, and a per-node table would need its own retention story on
    # top of the run's.
    nodes: list[dict[str, Any]] = SQLField(
        default_factory=list,
        sa_column=Column(
            postgresql.JSONB(astext_type=JSON()).with_variant(JSON(), "sqlite"),
            nullable=False,
            server_default="[]",
        ),
    )
    # The one nullable JSON column in this app, and it needs ``none_as_null`` to be
    # honest about it. SQLAlchemy's JSON types default to storing a Python ``None`` as
    # the JSON scalar ``null``, so without this a full-estate run is written as
    # ``'null'::jsonb`` and `WHERE scope IS NULL` finds none of them -- the Python side
    # reads back ``None`` either way, so nothing complains until someone asks the
    # database which runs were full sweeps. Measured happening before it was set.
    scope: list[str] | None = SQLField(
        default=None,
        sa_column=Column(
            postgresql.JSONB(astext_type=JSON(), none_as_null=True).with_variant(
                JSON(none_as_null=True), "sqlite"
            ),
            nullable=True,
        ),
    )
    error: str | None = SQLField(default=None)
