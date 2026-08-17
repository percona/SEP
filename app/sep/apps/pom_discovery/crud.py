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

"""Define reads and writes for the POM Discovery tables.

The entity upserts here are where §5.4's freshness lifecycle actually lives, and
they are written attribute by attribute on purpose. Nothing in these tables is
user-writable *yet*; the moment one field is -- an assigned name, a label, a
suppression flag -- a blanket "update every column" upsert wipes it on the next
sweep, and the test that catches that has to exist before the field does, not after.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.core.db.crud import BaseSQLModelManager
from app.core.utils.date_time import utc_now
from app.sep.apps.pom_discovery.models import (
    ObservedEntity,
    PomHost,
    PomService,
    ProbeRun,
    ProbeRunStatus,
)


class ProbeRunManager(BaseSQLModelManager):
    """Manage :class:`ProbeRun` CRUD operations.

    :cvar Model: The SQLModel class this manager is responsible for.
    """

    Model = ProbeRun


def _apply_attempt(
    entity: ObservedEntity,
    *,
    observed: dict[str, Any] | None,
    error: str | None,
    run_id: UUID | None,
) -> None:
    """Fold one attempt's outcome into an entity's freshness columns.

    Shared by both tables so they cannot drift apart, and the four rules it enforces
    are each cheap here and expensive to discover later:

    * ``failing_since`` is only set when it is unset. Overwriting it on every failure
      turns "since" into "most recent failure", so the duration is always about one
      schedule interval and the column stops being worth reading.
    * A failure does **not** touch ``observed``. The last known good document stays,
      with its own ``collected_at``, because what a host was running when it was last
      reachable is exactly what is wanted while it is not.
    * ``last_attempt_at`` moves on every attempt, ``last_success_at`` only on success.
      The gap between them is the answer to "how stale is this".
    * The caller decides what counts as an attempt. An entity a run did not target
      must never reach this function, or a single-host refresh marks the rest of the
      estate failed.

    :param entity: The row to update, already loaded.
    :param observed: The collected document on success; ``None`` on failure.
    :param error: The failure detail; ``None`` on success.
    :param run_id: The run this attempt belongs to.
    """
    now = utc_now()
    entity.last_attempt_at = now
    entity.last_run_id = run_id
    entity.updated_at = now

    if observed is not None:
        entity.observed = observed
        entity.last_success_at = now
        entity.failing_since = None
        entity.consecutive_failures = 0
        entity.last_error = None
        return

    entity.failing_since = entity.failing_since or now
    entity.consecutive_failures += 1
    entity.last_error = error


async def upsert_host(
    session: AsyncSession,
    *,
    node_id: str,
    name: str,
    address: str | None,
    executor_host: str | None,
    observed: dict[str, Any] | None = None,
    error: str | None = None,
    run_id: UUID | None = None,
    attempted: bool = True,
) -> PomHost:
    """Record one host, and optionally one attempt against it.

    Written whether or not any MongoDB was found on the host: that is what makes
    "which hosts have no database" a query rather than an absence, and it is the only
    way a host that has never run one appears at all.

    ``attempted`` is the difference between *seeing* an entity and *probing* it, and
    conflating the two is how a sweep starts lying. A host with no executor is seen
    every sweep and probed by none of them: its identity and its ``executor_host``
    are refreshed, and its attempt columns are left exactly where they were, so
    "unreachable for three days" stays readable and does not silently become
    "unreachable since the last sweep".

    :param session: The database session.
    :param node_id: PMM's node id.
    :param name: The node's registered name.
    :param address: The node's registered address.
    :param executor_host: The Nomad client serving it, or ``None``.
    :param observed: The collected document, or ``None`` when the attempt failed.
    :param error: The failure detail.
    :param run_id: The run this attempt belongs to.
    :param attempted: Whether this run actually probed the host.
    :return: The stored row.
    """
    host = await session.get(PomHost, node_id)
    if host is None:
        host = PomHost(node_id=node_id, name=name)
        session.add(host)

    # Identity attributes are owned by inventory and refreshed every time the host is
    # seen: a node that was renamed or readdressed should not keep reading as the old
    # one, and whether it currently has an executor is exactly the kind of thing a
    # reader needs even when nothing was run on it.
    host.name = name
    host.address = address
    host.executor_host = executor_host
    host.updated_at = utc_now()

    if attempted:
        _apply_attempt(host, observed=observed, error=error, run_id=run_id)
    return host


async def upsert_service(
    session: AsyncSession,
    *,
    service_id: str,
    node_id: str,
    name: str | None,
    port: int | None,
    role: str | None,
    observed: dict[str, Any] | None = None,
    error: str | None = None,
    run_id: UUID | None = None,
    attempted: bool = True,
) -> PomService:
    """Record one MongoDB service PMM has registered, and optionally one attempt.

    Every service PMM knows gets a row, including one whose host has no executor and
    could not be probed. Omitting those would report a healthier estate than exists --
    the PoC measured 17 of 18 services unreachable in a single run, and a listing that
    showed one service would have been worse than useless.

    ``role`` is only written when the probe determined one -- a failed attempt must
    not blank out what the last good one saw, for the same reason it must not blank
    out ``observed``.

    :param session: The database session.
    :param service_id: PMM's service id.
    :param node_id: The host it runs on; its ``pom.host`` row must exist.
    :param name: The service name.
    :param port: The port it listens on.
    :param role: The observed role, or ``None`` when this attempt did not see one.
    :param observed: The collected document, or ``None`` when the attempt failed.
    :param error: The failure detail.
    :param run_id: The run this attempt belongs to.
    :param attempted: Whether this run actually probed the service.
    :return: The stored row.
    """
    service = await session.get(PomService, service_id)
    if service is None:
        service = PomService(service_id=service_id, node_id=node_id)
        session.add(service)

    service.node_id = node_id
    service.name = name
    service.port = port
    service.updated_at = utc_now()
    if role is not None:
        service.role = role

    if attempted:
        _apply_attempt(service, observed=observed, error=error, run_id=run_id)
    return service


async def list_hosts(session: AsyncSession) -> list[PomHost]:
    """Return every host row, by name.

    :param session: The database session.
    :return: The hosts.
    """
    result = await session.exec(select(PomHost).order_by(col(PomHost.name)))
    return list(result.all())


async def list_services(
    session: AsyncSession, node_id: str | None = None
) -> list[PomService]:
    """Return service rows, optionally for one host.

    :param session: The database session.
    :param node_id: Restrict to this host when given.
    :return: The services.
    """
    statement = select(PomService).order_by(col(PomService.name))
    if node_id is not None:
        statement = statement.where(PomService.node_id == node_id)
    result = await session.exec(statement)
    return list(result.all())


#: Statuses a run can hold once it has stopped moving.
TERMINAL_STATUSES = (
    ProbeRunStatus.SUCCESS,
    ProbeRunStatus.PARTIAL,
    ProbeRunStatus.FAILED,
)


async def latest_terminal_run(session: AsyncSession) -> ProbeRun | None:
    """Return the newest run that finished, whatever it concluded.

    Deliberately not the newest run: a sweep in flight has no facts yet, and serving
    an empty set while one is running would make the consumer's merge lose every
    probe fact for the duration.

    :param session: The database session.
    :return: The run, or ``None`` when none has ever finished.
    """
    result = await session.exec(
        select(ProbeRun)
        .where(col(ProbeRun.status).in_(TERMINAL_STATUSES))
        .order_by(col(ProbeRun.started_at).desc())
        .limit(1)
    )
    return result.first()


async def recent_runs(session: AsyncSession, limit: int = 20) -> list[ProbeRun]:
    """Return the most recent runs, newest first.

    :param session: The database session.
    :param limit: How many to return.
    :return: The runs.
    """
    result = await session.exec(
        select(ProbeRun).order_by(col(ProbeRun.started_at).desc()).limit(limit)
    )
    return list(result.all())


async def get_run(session: AsyncSession, run_id: UUID) -> ProbeRun | None:
    """Return one run.

    :param session: The database session.
    :param run_id: The run's id.
    :return: The run, or ``None``.
    """
    return await session.get(ProbeRun, run_id)


async def running_run(session: AsyncSession) -> ProbeRun | None:
    """Return the sweep in flight, if there is one.

    :param session: The database session.
    :return: The running run, or ``None``.
    """
    result = await session.exec(
        select(ProbeRun)
        .where(ProbeRun.status == ProbeRunStatus.RUNNING)
        .order_by(col(ProbeRun.started_at).desc())
        .limit(1)
    )
    return result.first()


async def prune_runs(session: AsyncSession, keep: int) -> int:
    """Delete all but the newest ``keep`` runs.

    Every run carries its whole fact set, so the table grows by a few hundred
    kilobytes per sweep and needs bounding here rather than by an operator.

    :param session: The database session.
    :param keep: How many runs to keep.
    :return: The number deleted.
    """
    survivors = (
        select(ProbeRun.id).order_by(col(ProbeRun.started_at).desc()).limit(keep)
    )
    result = await session.exec(
        delete(ProbeRun).where(col(ProbeRun.id).not_in(survivors))  # type: ignore[call-overload]
    )
    await session.commit()
    return int(result.rowcount or 0)
