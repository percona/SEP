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

"""Define the POM Discovery persistence model.

One table. A run carries its whole fact set as JSONB rather than a row per fact:
the consumer reads a run's facts all at once or not at all, the set is a few hundred
small records, and a fact table would need its own retention story on top of the
run's.

The table lives in POM's own schema, declared *symbolically*: the models name the
token ``pom_schema`` and the engine translates it per bind (``app/sep/pom/config.py``).
A literal name would be uncreatable on SQLite, which has no schemas, and would escape
the per-worker schema the real-PostgreSQL test lane routes everything into.

This module is loaded by Alembic through ``spec_from_file_location`` without running
the package ``__init__``, so it must not import sibling app modules. That is also why
the schema below is a bare string rather than
``app.sep.pom.config.POM_SCHEMA_SYMBOL``: the token has to be spelled here, and
``sqlalchemy_celery_beat`` makes the same trade with ``celery_schema``.
"""

from enum import StrEnum
from typing import Any

from sqlalchemy import Column, JSON
from sqlalchemy import Enum as EnumField
from sqlalchemy.dialects import postgresql
from sqlmodel import Field as SQLField

from app.core.db.models import BaseUUIDSQLModel, DateTimeWithTimezone
from app.core.utils.date_time import utc_now
from app.core.utils.fields import UTCDatetime

#: The symbolic schema this app's tables declare. See the module docstring.
POM_SCHEMA = "pom_schema"

# The table name is short -- ``discovery_run`` -- because the schema is what qualifies
# it. It was ``pom_discovery_run`` while it sat in the default schema and the prefix
# was the only thing saying what it was; inside ``pom`` that is stutter.


class ProbeRunStatus(StrEnum):
    """Enumerate the states of one probe sweep.

    ``PARTIAL`` is the common steady state, not an alarm: the probe reaches only
    services whose node runs a healthy ``raw_exec`` executor, and an inventory row
    routinely outlives the executor that served it.

    :cvar RUNNING: The sweep is in flight.
    :cvar SUCCESS: Every service that resolved to a live executor answered.
    :cvar PARTIAL: Some answered, some did not.
    :cvar FAILED: None answered, or the sweep raised.
    """

    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


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


class ProbeRun(BaseUUIDSQLModel, table=True):
    """Record one probe sweep and the facts it collected.

    :param started_at: When the sweep began.
    :param finished_at: When it reached a terminal status; ``None`` while running.
    :param status: The sweep's lifecycle state.
    :param services_total: MongoDB services inventory reported.
    :param services_resolved: ...of which mapped to a live executor host.
    :param services_orphaned: ...of which did not. Not an error.
    :param services_answered: Services that returned a usable probe record.
    :param facts: The collected facts, each ``{service_id, field, value,
        observed_at}`` where ``service_id`` is **PMM's** service UUID -- the only key
        the consumer can join on, and the reason the API translates away SEP's own
        inventory id before storing.
    :param nodes: One record per mapped service: where it was probed, how that host
        was matched, whether it answered and how long its host took. The counters
        above are this list's summary, and a summary is all a sweep could show until
        this column existed -- "5 of 14 answered" cannot say *which* five, on which
        hosts, or which one took a minute.
    :param error: The failure detail when the sweep itself raised.
    """

    __tablename__ = "discovery_run"
    __table_args__ = {"schema": POM_SCHEMA}

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
    error: str | None = SQLField(default=None)
