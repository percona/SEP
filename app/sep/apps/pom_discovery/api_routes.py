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
    get_run,
    latest_terminal_run,
    ProbeRunManager,
    recent_runs,
    running_run,
)
from app.sep.apps.pom_discovery.models import ProbeRun, ProbeRunStatus
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
