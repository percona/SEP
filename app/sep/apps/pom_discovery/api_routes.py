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

"""Serve the probe's facts, and the runs that produced them.

``GET /facts`` is the contract with PMM, and its shape follows from one constraint:
**the caller must never wait for a Nomad job.** PMM assembles its topology document
on the request path in about a tenth of a second; a probe sweep takes tens of
seconds. So this endpoint never probes. It serves whatever the last completed sweep
stored, says how old that is, and leaves the caller to decide -- which it can,
because every fact carries its own ``observed_at`` and the consumer merges by
precedence rather than by trust.

Auth is applied at the mount level: ``/api/apps`` carries the ``IsApiAuthenticated``
router guard, and unsafe methods additionally require a bearer.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field

from app.core.exceptions import HTTPConflictException, HTTPNotFoundException
from app.core.utils.date_time import utc_now
from app.sep.apps.framework.api import schema_endpoint
from app.sep.apps.pom_discovery.config import pom_discovery_settings
from app.sep.apps.pom_discovery.crud import (
    delete_host,
    delete_service,
    get_host,
    get_run,
    get_service,
    latest_terminal_run,
    list_hosts,
    list_services,
    ProbeRunManager,
    recent_runs,
    running_run,
)
from app.sep.apps.pom_discovery.models import (
    PomHost,
    PomService,
    ProbeRun,
    ProbeRunStatus,
)
from app.sep.apps.pom_discovery.schema import pom_discovery_schema
from app.sep.deps import SessionDep

router = APIRouter()
schema_endpoint(router=router, plugin_schema=pom_discovery_schema)


class ProbeFact(BaseModel):
    """One fact about one service, as the probe saw it.

    :param service_id: **PMM's** service UUID. The consumer joins on this; SEP's own
        inventory id would mean nothing on the other side.
    :param field: The document field this sets, e.g. ``installed_version``.
    :param value: The observed value.
    :param observed_at: When the probe ran. Carried per fact rather than per response
        so a consumer merging several sources can age them against each other.
    """

    service_id: str
    field: str
    value: Any
    observed_at: datetime


class ProbeCounts(BaseModel):
    """Count what one sweep reached.

    ``resolved`` versus ``answered`` is the diagnostic split: the first says the
    service mapped to a live executor host, the second says the node ran the payload.
    A sweep with ``resolved=9, answered=0`` is a healthy mapping and broken executors.

    :param services_total: MongoDB services inventory reported.
    :param services_resolved: ...of which mapped to a live executor host.
    :param services_orphaned: ...of which did not. Not an error.
    :param services_answered: Services that returned a usable probe record.
    """

    services_total: int
    services_resolved: int
    services_orphaned: int
    services_answered: int


class FactsResponse(BaseModel):
    """Everything the last completed sweep found.

    :param run_id: The sweep that produced these facts.
    :param status: That sweep's terminal status.
    :param observed_at: When it ran, or ``None`` when none has ever completed.
    :param age_seconds: How long ago that was.
    :param stale: Whether it is older than ``FACTS_MAX_AGE``. Advisory: the facts are
        served either way, because discarding them would erase the difference between
        "this node has no probe" and "this node has not been probed since Tuesday".
    :param counts: What the sweep reached.
    :param facts: The facts themselves.
    :param error: Why the sweep failed, when it did. Carried here rather than left in
        the run history so a consumer can report the cause in its own receipt instead
        of saying only that the facts are missing.
    """

    run_id: UUID | None = None
    status: str | None = None
    observed_at: datetime | None = None
    age_seconds: float | None = None
    stale: bool = False
    counts: ProbeCounts | None = None
    facts: list[ProbeFact] = Field(default_factory=list)
    error: str | None = None


class ProbeRunResponse(BaseModel):
    """One sweep's record.

    :param run_id: The sweep's id.
    :param status: ``running`` / ``success`` / ``partial`` / ``failed``.
    :param started_at: When it began.
    :param finished_at: When it reached a terminal status; ``None`` while running.
    :param counts: What it reached.
    :param facts_collected: How many facts it stored.
    :param error: The failure detail when the sweep itself raised.
    """

    run_id: UUID
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    counts: ProbeCounts
    facts_collected: int = 0
    error: str | None = None


class ProbeNode(BaseModel):
    """One mapped service, as this sweep saw it.

    The counters on the run are this list's summary; these are the rows behind them.
    "5 of 14 answered" cannot say which five, on which hosts, or which host took a
    minute, and every one of those is the first question asked of a slow or partial
    sweep.

    :param service_id: **PMM's** service UUID, or ``None`` where inventory holds
        none — which is also why such a service contributes no facts.
    :param service_name: The service's name, carried so a reader is not left joining
        UUIDs by hand.
    :param executor_host: The host its probe ran on; ``None`` when orphaned.
    :param resolution: ``name`` / ``address`` / ``orphaned`` — how that host was
        matched, or that it was not.
    :param answered: Whether the host returned a usable record for this service.
    :param duration_seconds: The host's wall-clock, dispatch to collected output.
        Repeated across the services one host serves: a single dispatch covers all of
        them, so there is no per-service time to report.
    :param facts_collected: How many facts this service contributed.
    :param error: The host-level failure, when its probe failed.
    """

    service_id: str | None = None
    service_name: str
    executor_host: str | None = None
    resolution: str
    answered: bool
    duration_seconds: float | None = None
    facts_collected: int = 0
    error: str | None = None


class ProbeRunDetail(ProbeRunResponse):
    """One sweep, with everything it recorded.

    Kept apart from the list shape on purpose: a sweep's facts run to a few hundred
    records, so returning them for every row of a 25-run history would make the list
    an order of magnitude larger to serve a page that shows one run at a time.

    :param nodes: What the sweep saw per service.
    :param facts: The facts it collected — every field the probe reads, including the
        ones no consumer maps today.
    """

    nodes: list[ProbeNode] = Field(default_factory=list)
    facts: list[ProbeFact] = Field(default_factory=list)


class ProbeRunAccepted(BaseModel):
    """Acknowledge a queued sweep.

    Returned with ``202``: a sweep dispatches Nomad jobs and takes tens of seconds, so
    it is never performed synchronously.

    :param run_id: The queued sweep's id.
    :param status: Always ``running`` at this point.
    :param started_at: When the run row was created.
    """

    run_id: UUID
    status: str
    started_at: datetime


class ServiceResponse(BaseModel):
    """One MongoDB service PMM has registered, as POM currently holds it.

    Keyed on **PMM's** service id, which is the whole benefit of storing it that way:
    the path and the payload carry the id every consumer already has, with nothing to
    translate on either side.

    :param service_id: PMM's service id.
    :param node_id: The host it runs on.
    :param name: The service name as PMM registered it.
    :param port: The port it listens on.
    :param role: What the probe found it to be, when a probe determined one.
    :param observed: Everything collected, with its own ``collected_at``. Empty when
        this service has never been successfully probed.
    :param first_seen_at: When POM first wrote a row for it.
    :param last_attempt_at: When a run last targeted it. ``None`` means no run ever
        has, which is different from having tried and failed.
    :param last_success_at: When it last answered. This is the data's age.
    :param failing_since: The first failure after the last success; ``None`` while
        healthy.
    :param consecutive_failures: Failures since the last success.
    :param last_error: The most recent failure detail.
    """

    service_id: str
    node_id: str
    name: str | None = None
    port: int | None = None
    role: str | None = None
    observed: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    failing_since: datetime | None = None
    consecutive_failures: int = 0
    last_error: str | None = None


class HostResponse(BaseModel):
    """One host, with the services POM knows are on it.

    A host is a row whether or not any MongoDB was found on it: that is what makes
    "which hosts have no database" a query rather than an absence, and it is the only
    way a machine that has never run one appears at all.

    :param node_id: PMM's node id.
    :param name: The node's registered name.
    :param address: The node's registered address.
    :param executor_host: The Nomad client serving it. ``None`` means nothing can be
        run there, which is a fact about the estate rather than a probe failure.
    :param observed: Everything collected about the host, including
        ``unregistered_mongods`` where the probe found a database PMM has no service
        for. Empty when the host has never been successfully probed.
    :param first_seen_at: When POM first wrote a row for it.
    :param last_attempt_at: When a run last probed it.
    :param last_success_at: When it last answered.
    :param failing_since: The first failure after the last success.
    :param consecutive_failures: Failures since the last success.
    :param last_error: The most recent failure detail.
    :param services: The services on it. Empty is a meaningful answer, not a gap.
    """

    node_id: str
    name: str
    address: str | None = None
    executor_host: str | None = None
    observed: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    failing_since: datetime | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    services: list[ServiceResponse] = Field(default_factory=list)


def _service_response(service: PomService) -> ServiceResponse:
    """Project one service row for the wire.

    :param service: The stored row.
    :return: The response.
    """
    return ServiceResponse(
        service_id=service.service_id,
        node_id=service.node_id,
        name=service.name,
        port=service.port,
        role=service.role,
        observed=service.observed or {},
        first_seen_at=service.first_seen_at,
        last_attempt_at=service.last_attempt_at,
        last_success_at=service.last_success_at,
        failing_since=service.failing_since,
        consecutive_failures=service.consecutive_failures,
        last_error=service.last_error,
    )


def _host_response(host: PomHost, services: list[PomService]) -> HostResponse:
    """Project one host row, with its services nested.

    :param host: The stored row.
    :param services: Its service rows.
    :return: The response.
    """
    return HostResponse(
        node_id=host.node_id,
        name=host.name,
        address=host.address,
        executor_host=host.executor_host,
        observed=host.observed or {},
        first_seen_at=host.first_seen_at,
        last_attempt_at=host.last_attempt_at,
        last_success_at=host.last_success_at,
        failing_since=host.failing_since,
        consecutive_failures=host.consecutive_failures,
        last_error=host.last_error,
        services=[_service_response(service) for service in services],
    )


def _counts(run: ProbeRun) -> ProbeCounts:
    """Project a run's counters.

    :param run: The run.
    :return: Its counts.
    """
    return ProbeCounts(
        services_total=run.services_total,
        services_resolved=run.services_resolved,
        services_orphaned=run.services_orphaned,
        services_answered=run.services_answered,
    )


def _run_response(run: ProbeRun) -> ProbeRunResponse:
    """Project one run for the wire.

    :param run: The run.
    :return: The response.
    """
    return ProbeRunResponse(
        run_id=run.id,
        status=str(run.status),
        started_at=run.started_at,
        finished_at=run.finished_at,
        counts=_counts(run),
        facts_collected=len(run.facts or []),
        error=run.error,
    )


@router.get("/hosts", response_model=list[HostResponse])
async def list_estate_hosts(
    session: SessionDep,
    has_service: bool | None = Query(
        default=None,
        description="True for hosts running a MongoDB service, False for those with "
        "none. Omit for all of them.",
    ),
    failing: bool | None = Query(
        default=None, description="Restrict to hosts that are, or are not, failing."
    ),
    executor: bool | None = Query(
        default=None,
        description="True for hosts a payload can run on, False for those with no "
        "executor.",
    ),
) -> list[HostResponse]:
    """Return every host POM holds, each with its services.

    ``has_service=false`` is the question this table exists to answer: which machines
    carry a PMM client and no database. It is a filter rather than an endpoint of its
    own so there is one list contract to learn, and because the same list with the
    filter inverted is the ordinary estate view.

    Counts describe the *tables*, not the last run. A scoped refresh must not make the
    estate look one host wide.

    :param session: The database session.
    :param has_service: Filter on whether a MongoDB service is registered here.
    :param failing: Filter on whether the host is currently failing.
    :param executor: Filter on whether an executor serves it.
    :return: The hosts, by name.
    """
    hosts = await list_hosts(session)
    services = await list_services(session)

    by_node: dict[str, list[PomService]] = {}
    for service in services:
        by_node.setdefault(service.node_id, []).append(service)

    return [
        _host_response(host, by_node.get(host.node_id, []))
        for host in hosts
        if (has_service is None or bool(by_node.get(host.node_id)) is has_service)
        and (failing is None or (host.failing_since is not None) is failing)
        and (executor is None or (host.executor_host is not None) is executor)
    ]


@router.get("/hosts/{node_id}", response_model=HostResponse)
async def get_estate_host(node_id: str, session: SessionDep) -> HostResponse:
    """Return one host, with its services.

    :param node_id: PMM's node id.
    :param session: The database session.
    :raises HTTPNotFoundException: When POM holds no such host.
    :return: The host.
    """
    host = await get_host(session, node_id)
    if host is None:
        raise HTTPNotFoundException(detail=f"Host {node_id} not found")
    return _host_response(host, await list_services(session, node_id=node_id))


@router.get("/services", response_model=list[ServiceResponse])
async def list_estate_services(
    session: SessionDep,
    node_id: str | None = Query(default=None, description="Restrict to one host."),
    failing: bool | None = Query(
        default=None, description="Restrict to services that are, or are not, failing."
    ),
) -> list[ServiceResponse]:
    """Return the services POM holds, flat.

    For a consumer that works in services and would otherwise walk every host document
    to find them. ``GET /hosts/{node_id}`` already nests a host's services, so there is
    deliberately no ``/hosts/{node_id}/services``: it would be a second spelling of the
    same list, and ``?node_id=`` covers wanting them without the host.

    :param session: The database session.
    :param node_id: Restrict to one host.
    :param failing: Filter on whether the service is currently failing.
    :return: The services, by name.
    """
    return [
        _service_response(service)
        for service in await list_services(session, node_id=node_id)
        if failing is None or (service.failing_since is not None) is failing
    ]


@router.get("/services/{service_id}", response_model=ServiceResponse)
async def get_estate_service(service_id: str, session: SessionDep) -> ServiceResponse:
    """Return one service, by PMM's service id.

    :param service_id: PMM's service id.
    :param session: The database session.
    :raises HTTPNotFoundException: When POM holds no such service.
    :return: The service.
    """
    service = await get_service(session, service_id)
    if service is None:
        raise HTTPNotFoundException(detail=f"Service {service_id} not found")
    return _service_response(service)


@router.delete("/hosts/{node_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_estate_host(node_id: str, session: SessionDep) -> None:
    """Forget one host, and by cascade its services.

    For rows PMM no longer has, which is not hypothetical: restarting a node's
    pmm-agent runs ``setup --force``, which *replaces* the node and mints a new id, so
    POM gains a row and keeps the old one. Nothing prunes automatically yet, and the
    alternative to this endpoint is ``psql`` against a schema an operator should never
    need to know exists.

    Deliberately not suppression. An entity PMM still knows about comes straight back
    on the next sweep, because POM's job is to describe what PMM says exists, not to
    hold an opinion about it.

    Its services go with it. That is done explicitly rather than left to the
    ``ON DELETE CASCADE`` on ``pom.service.node_id``, because SQLite enforces no
    foreign key without a per-connection pragma SEP never sets -- and SQLite is the
    shipped default. See :func:`~app.sep.apps.pom_discovery.crud.delete_host`.

    :param node_id: PMM's node id.
    :param session: The database session.
    :raises HTTPNotFoundException: When POM holds no such host.
    """
    host = await get_host(session, node_id)
    if host is None:
        raise HTTPNotFoundException(detail=f"Host {node_id} not found")
    await delete_host(session, host)


@router.delete("/services/{service_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_estate_service(service_id: str, session: SessionDep) -> None:
    """Forget one service, leaving its host alone.

    Same contract as deleting a host: for a row PMM no longer has, and no defence
    against one it still does.

    :param service_id: PMM's service id.
    :param session: The database session.
    :raises HTTPNotFoundException: When POM holds no such service.
    """
    service = await get_service(session, service_id)
    if service is None:
        raise HTTPNotFoundException(detail=f"Service {service_id} not found")
    await delete_service(session, service)


@router.get("/facts", response_model=FactsResponse)
async def get_facts(session: SessionDep) -> FactsResponse:
    """Return the facts from the last completed sweep.

    Answers ``200`` with an empty fact list when the probe has never completed, rather
    than ``404``: "no probe has run here" is a normal state of a PMM that has not
    enabled this app, and a consumer should record the source as empty rather than
    treat its own configuration as broken.

    :param session: The database session.
    :return: The facts, with their age.
    """
    run = await latest_terminal_run(session)
    if run is None:
        return FactsResponse()

    observed_at = run.finished_at or run.started_at
    age = (utc_now() - observed_at).total_seconds()
    return FactsResponse(
        run_id=run.id,
        status=str(run.status),
        observed_at=observed_at,
        age_seconds=age,
        stale=age > pom_discovery_settings.FACTS_MAX_AGE.total_seconds(),
        counts=_counts(run),
        facts=[ProbeFact(**fact) for fact in (run.facts or [])],
        error=run.error,
    )


@router.get("/runs", response_model=list[ProbeRunResponse])
async def list_runs(
    session: SessionDep, limit: int = Query(default=20, ge=1, le=100)
) -> list[ProbeRunResponse]:
    """Return recent sweeps, newest first.

    :param session: The database session.
    :param limit: How many to return.
    :return: The sweeps.
    """
    return [_run_response(run) for run in await recent_runs(session, limit)]


@router.get("/runs/{run_id}", response_model=ProbeRunDetail)
async def get_probe_run(run_id: UUID, session: SessionDep) -> ProbeRunDetail:
    """Return one sweep, with its per-service records and its facts.

    :param run_id: The sweep's id.
    :param session: The database session.
    :raises HTTPNotFoundException: When there is no such sweep.
    :return: The sweep in full.
    """
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPNotFoundException(detail=f"Probe run {run_id} not found")
    return ProbeRunDetail(
        **_run_response(run).model_dump(),
        # Runs recorded before `nodes` existed have none, and answer with an empty
        # list rather than a 500: an old sweep is still worth its counters.
        nodes=[ProbeNode(**node) for node in (run.nodes or [])],
        facts=[ProbeFact(**fact) for fact in (run.facts or [])],
    )


@router.post(
    "/runs",
    response_model=ProbeRunAccepted,
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def trigger_probe(session: SessionDep) -> ProbeRunAccepted:
    """Queue a probe sweep.

    :param session: The database session.
    :raises HTTPConflictException: When a sweep is already in flight.
    :return: The queued sweep.
    """
    in_flight = await running_run(session)
    if in_flight is not None:
        age = utc_now() - in_flight.started_at
        if age < pom_discovery_settings.STALE_RUN_AFTER:
            raise HTTPConflictException(
                detail=f"Probe run {in_flight.id} is already in flight"
            )
        # Past the cutoff its worker is gone, and nothing else would ever advance the
        # row. Fail it here so one lost worker cannot wedge the app indefinitely.
        in_flight.status = ProbeRunStatus.FAILED
        in_flight.finished_at = utc_now()
        in_flight.error = "abandoned: no worker recorded a terminal status"
        await ProbeRunManager.save(session, in_flight)

    run = await ProbeRunManager.save(session, ProbeRun())

    # Imported here rather than at module scope: the API process has no reason to load
    # the dispatch stack, and importing celery.py at import time would pull it in.
    from app.sep.apps.pom_discovery.celery import run_pom_probe

    run_pom_probe.delay(str(run.id))
    return ProbeRunAccepted(
        run_id=run.id, status=str(run.status), started_at=run.started_at
    )
