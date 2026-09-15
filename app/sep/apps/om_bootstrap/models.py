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

"""Define the OpenManager Bootstrap persistence model.

One table, and the design is the same call ``om_inventory``'s ``ProbeRun`` makes
(PMM-15347/plan.md §4 item 9: ``om_bootstrap`` owns durable state): ``hosts`` is a
JSON document of :class:`~app.sep.apps.om_bootstrap.strategy.HostBootstrapState`
rows rather than a normalized per-step table. A per-step table would need a fixed
column for "step name", but the step list itself is per-strategy and per-spec
(``InstallStrategy.plan_steps`` -- see ``strategy.py``'s module docstring), so
there is no fixed shape to normalize into; a migration would be needed every time
a strategy's step list changed.

A run reads and writes its ``hosts`` document whole, never a single step in
isolation -- exactly the access pattern ``nodes`` on ``ProbeRun`` already commits
to for the same reason.

This module is loaded by Alembic through ``spec_from_file_location`` without
running the package ``__init__`` -- and, critically, must not undo that by
importing *any* sibling module through the ``app.sep.apps.om_bootstrap`` package
path, ``strategy`` included: resolving that dotted path still forces Python to
import-and-run ``om_bootstrap/__init__.py`` first, which pulls in ``app.py`` and
the whole framework. ``om_inventory/models.py`` avoids this the same way -- zero
imports from within its own package -- which is why :data:`OM_SCHEMA` below is a
bare string rather than an imported symbol, and why ``InstallMethod``/
``OperatingSystem`` are spelled again here rather than imported from
:mod:`~app.sep.apps.om_bootstrap.strategy`, their real home. Conversion between
this module's persisted shape and ``strategy``'s typed shape lives in
``persistence.py`` instead, which is never Alembic-loaded and so carries no such
restriction.
"""

from enum import StrEnum
from typing import Any

from sqlalchemy import Column, JSON, Text
from sqlalchemy import Enum as EnumField
from sqlalchemy.dialects import postgresql
from sqlmodel import Field as SQLField

from app.core.db.models import BaseUUIDSQLModel, DateTimeWithTimezone
from app.core.utils.date_time import utc_now
from app.core.utils.fields import UTCDatetime

#: Spelled again from ``strategy.InstallMethod`` -- see the module docstring for
#: why this cannot be an import. Keep the two in sync by hand;
#: ``persistence.py`` asserts they match.
InstallMethod = StrEnum(
    "InstallMethod", {"PACKAGES": "packages", "DOCKER": "docker", "PODMAN": "podman"}
)

#: Spelled again from ``strategy.OperatingSystem`` -- see the module docstring
#: for why this cannot be an import.
OperatingSystem = StrEnum("OperatingSystem", {"UBUNTU": "ubuntu", "ROCKY": "rocky"})

#: The symbolic schema this table declares -- the same token ``om_inventory``
#: uses, translated to the same real ``om`` schema. ``om_bootstrap`` is a
#: different app but the same OM feature area; splitting its tables into a
#: second schema would buy no isolation ``om_inventory`` doesn't already have
#: from SEP's own core tables, and would cost every cross-app query a second
#: schema to know about.
OM_SCHEMA = "om_schema"


class BootstrapRunStatus(StrEnum):
    """Enumerate the states of one bootstrap run.

    Matches Adamo's decided partial-failure policy exactly
    (PMM-15347/questions.md Q8): retry a failed host, and if retries are
    exhausted, roll back the whole run -- there is no "partial success" status
    here the way ``ProbeRun.PARTIAL`` is a normal steady state for a sweep. A
    bootstrap either finishes with every host succeeded, or it did not finish.

    :cvar RUNNING: The run is in flight -- pre-flight checks, installing,
        configuring, or verifying on at least one host.
    :cvar SUCCEEDED: Every host reached :attr:`~app.sep.apps.om_bootstrap.strategy.StepStatus.SUCCEEDED`.
    :cvar FAILED: A host failed and retries were exhausted; rollback has not
        (yet, or ever) run.
    :cvar ROLLED_BACK: A failure's rollback completed.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class BootstrapRun(BaseUUIDSQLModel, table=True):
    """Record one provisioning run: a spec, its planned steps, applied to hosts.

    Created with every host's planned steps already known
    (:meth:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy.plan_steps` is
    called once, up front, per host) -- so a caller reading a fresh run
    immediately knows its full step list, not just the ones that have started.

    :param started_at: When the run began.
    :param finished_at: When it reached a terminal status; ``None`` while running.
    :param status: The run's lifecycle state.
    :param install_method: Which :class:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy`
        this run uses -- fixed for the whole run, not per-host: every host in one
        replica set is provisioned the same way.
    :param os: The target hosts' OS. Fixed for the whole run for the same reason
        as ``install_method`` -- a replica set with mixed OSes is out of
        phase-1 scope.
    :param mongodb_version: The Percona Server for MongoDB version this run
        installs.
    :param replica_set_name: The replica set every host in this run joins.
    :param hosts: One :class:`~app.sep.apps.om_bootstrap.strategy.HostBootstrapState`
        per host, as plain JSON (``model_dump()``, not re-validated on read --
        callers that need the typed shape back use
        :func:`~app.sep.apps.om_bootstrap.persistence.parse_host_states`). Read
        and written whole; see the module docstring for why this is not a
        normalized per-step table.
    :param error: The failure detail when the run itself raised, outside any
        single host's steps -- e.g. a spec that failed validation before any
        host was touched.
    """

    __tablename__ = "bootstrap_run"
    # A *symbolic* schema, translated per bind by the engine
    # (``app/sep/apps/shared/om/config.py``). See ``om_inventory/models.py``'s own
    # ``ProbeRun`` for why this is never a literal schema name.
    __table_args__ = {"schema": OM_SCHEMA}

    started_at: UTCDatetime = SQLField(
        sa_type=DateTimeWithTimezone, default_factory=utc_now, index=True
    )
    finished_at: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )
    status: BootstrapRunStatus = SQLField(
        default=BootstrapRunStatus.RUNNING,
        sa_column=Column(
            EnumField(BootstrapRunStatus, native_enum=False, create_constraint=True),
            nullable=False,
            index=True,
        ),
    )

    install_method: InstallMethod = SQLField(
        sa_column=Column(
            EnumField(InstallMethod, native_enum=False, create_constraint=True),
            nullable=False,
        ),
    )
    os: OperatingSystem = SQLField(
        sa_column=Column(
            EnumField(OperatingSystem, native_enum=False, create_constraint=True),
            nullable=False,
        ),
    )
    mongodb_version: str
    replica_set_name: str = SQLField(sa_type=Text)

    # JSON, not postgresql.JSONB directly: PostgreSQL is the dialect that gets a
    # variant carved out of it here, same reasoning as ProbeRun.nodes.
    hosts: list[dict[str, Any]] = SQLField(
        default_factory=list,
        sa_column=Column(
            JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
    )
    error: str | None = SQLField(default=None)
