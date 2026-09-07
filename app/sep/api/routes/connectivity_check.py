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

"""Define the admin-only ``/api/sep/admin/connectivity-check`` endpoint.

Expose a single generic ``POST`` that probes the caller-specified external /
inter-service endpoints (PMM, Inventory, Tasks, Nomad, and the diagnostics
delivery receiver) on demand and reports normalized per-endpoint connectivity
status, so an admin can confirm an endpoint or credential change is reachable
and valid before relying on it. The request must name which services to probe
(``targets``, required, no default), so the settings flow can validate only the
endpoint being edited while a full sweep still names them all.

The probes are driven by the overridable ``RemoteAPI.check_connectivity``
capability and fan out concurrently. A failure for one endpoint is captured and
classified independently, so a single outage never fails the whole response.
PMM, Inventory, and Tasks are built through the existing
``settings.get_remote_api`` / ``ClientRegistry`` path (honoring SSL config and
hot-reloaded overrides); Nomad reuses the Tasks ``/hosts/`` proxy -- a healthy
response proves both Tasks and Nomad are reachable, so no new Tasks-app endpoint
is added. Because Tasks and Nomad share that single probe, requesting either (or
both) runs ``/hosts/`` exactly once.
"""

import asyncio
from enum import StrEnum

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.exceptions import HTTPBadGatewayException
from app.core.requests.connectivity import (
    build_connectivity_result,
    classify_connectivity_error,
    ConnectivityResult,
    ConnectivityStatusEnum,
    EXTERNAL_PROBE_TIMEOUT_SECONDS,
    PROBE_TIMEOUT_SECONDS,
)
from app.core.requests.remote_api import UPSTREAM_NON_JSON_HEADER
from app.sep.bundle_upload.factory import get_delivery_executor
from app.sep.bundle_upload.resolver import (
    DeliveryUnavailableCode,
    resolve_delivery_plan,
)
from app.sep.deps import InventoryAPI, PMMAPIDep, TaskAPI

router = APIRouter()


class ServiceEnum(StrEnum):
    """Enumerate the probeable services, used as stable ``service`` identifiers."""

    PMM = "pmm"
    INVENTORY = "inventory"
    TASKS = "tasks"
    NOMAD = "nomad"
    DELIVERY = "delivery"


class ConnectivityCheckRequest(BaseModel):
    """Carry the required set of services to probe.

    :param targets: The services to probe. Must name at least one; duplicates are
        collapsed so a shared probe (Tasks/Nomad) still runs once.
    """

    targets: list[ServiceEnum] = Field(min_length=1)


#: Authenticated Inventory route used as the reachability probe. ``/summary/``
#: requires auth, so it also exercises authentication-failure detection.
_INVENTORY_PROBE_PATH = "/summary/"

#: Tasks route that aggregates executor hosts. A ``200`` (even an empty mapping)
#: proves both the Tasks API and Nomad are reachable; an upstream ``502`` proves
#: Tasks is up but Nomad is unreachable.
_HOSTS_PROBE_PATH = "/hosts/"


async def _probe_pmm(pmm_api: PMMAPIDep) -> ConnectivityResult:
    """Probe PMM, or report "not configured" when no endpoint/key is set.

    :param pmm_api: The PMM client, or ``None`` when PMM is unconfigured.
    :return: The PMM connectivity result.
    """
    if pmm_api is None:
        return build_connectivity_result(
            ServiceEnum.PMM,
            ConnectivityStatusEnum.NOT_CONFIGURED,
            detail="PMM is not configured.",
        )
    return await pmm_api.check_connectivity(ServiceEnum.PMM)


async def _probe_tasks_and_nomad(
    tasks_api: TaskAPI,
) -> tuple[ConnectivityResult, ConnectivityResult]:
    """Derive both Tasks and Nomad results from a single ``/hosts/`` probe.

    A ``200`` (including an empty cluster) means both are reachable. Only an
    *app-level* ``502 Bad Gateway`` -- the Tasks app answered with a JSON error
    because its executor backend is unreachable -- means Tasks is reachable
    while Nomad is not. A ``502`` with a non-JSON body is nginx answering
    because the whole Tasks app is down; it carries the
    :data:`UPSTREAM_NON_JSON_HEADER` marker and is classified as Tasks
    unreachable. Any other failure (other HTTP errors such as a ``500``
    indicating an unhealthy Tasks API itself, plus connection-level / SSL /
    timeout / auth failures) applies to both, since a healthy Tasks API cannot
    be confirmed and Nomad therefore cannot be either.

    :param tasks_api: The authenticated Tasks API client.
    :return: A ``(tasks_result, nomad_result)`` pair.
    """
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await tasks_api.get(_HOSTS_PROBE_PATH)
    except Exception as exc:  # noqa: BLE001 -- classified, never re-raised
        if isinstance(exc, HTTPBadGatewayException) and not (exc.headers or {}).get(
            UPSTREAM_NON_JSON_HEADER
        ):
            # The Tasks app answered with a JSON 502 but its executor backend is
            # down, so Tasks is reachable but Nomad is not. A bare non-JSON 502
            # (nginx, Tasks app down) carries the marker header and falls through.
            return (
                build_connectivity_result(
                    ServiceEnum.TASKS, ConnectivityStatusEnum.REACHABLE
                ),
                build_connectivity_result(
                    ServiceEnum.NOMAD,
                    ConnectivityStatusEnum.UNREACHABLE,
                    detail="Executor backend unreachable.",
                ),
            )
        # The Tasks endpoint itself failed (HTTP 5xx other than 502, connection,
        # SSL, timeout, or auth); Nomad cannot be confirmed either.
        probe_status = classify_connectivity_error(exc)
        return (
            build_connectivity_result(ServiceEnum.TASKS, probe_status),
            build_connectivity_result(ServiceEnum.NOMAD, probe_status),
        )
    return (
        build_connectivity_result(ServiceEnum.TASKS, ConnectivityStatusEnum.REACHABLE),
        build_connectivity_result(ServiceEnum.NOMAD, ConnectivityStatusEnum.REACHABLE),
    )


#: The connectivity status each unavailability code reports as. Delivery being
#: unconfigured and its stored inputs having drifted are separate outcomes
#: because only the second is fixed by re-supplying the inputs.
_DELIVERY_UNAVAILABLE_STATUS: dict[DeliveryUnavailableCode, ConnectivityStatusEnum] = {
    DeliveryUnavailableCode.UNCONFIGURED: ConnectivityStatusEnum.NOT_CONFIGURED,
    DeliveryUnavailableCode.DRIFTED_INPUTS: ConnectivityStatusEnum.INPUTS_DRIFTED,
}


async def _probe_delivery() -> ConnectivityResult:
    """Report whether the configured diagnostics-delivery receiver answers.

    Issues the delivery plan's own declared probe request rather than replaying
    its send steps: a resolution step may mutate state, and its values may cite
    inputs that exist only during a real send. A plan that declares no probe is
    reported as such instead of being guessed at.

    The resolver's prose reason is passed through verbatim as the detail, while
    the status carries the same distinction machine-readably.

    Branches on the resolution's code rather than its plan, so the unavailable
    outcomes map through one table instead of being re-derived from the prose.
    That branch narrows nothing for a type checker, so the ``plan is None`` arm
    below is what narrows the optional in place of an assertion; the
    resolution's own invariant is what makes that arm unreachable.

    :return: The delivery connectivity result.
    """
    resolution = resolve_delivery_plan()
    if (code := resolution.code) is not None:
        return build_connectivity_result(
            ServiceEnum.DELIVERY,
            _DELIVERY_UNAVAILABLE_STATUS[code],
            detail=resolution.unavailable_reason,
        )
    plan = resolution.plan
    if plan is None or plan.probe is None:
        return build_connectivity_result(
            ServiceEnum.DELIVERY, ConnectivityStatusEnum.PROBE_UNDECLARED
        )
    try:
        async with asyncio.timeout(EXTERNAL_PROBE_TIMEOUT_SECONDS):
            async with get_delivery_executor(plan) as executor:
                await executor.probe()
    except Exception as exc:  # noqa: BLE001 -- classified, never re-raised
        return build_connectivity_result(
            ServiceEnum.DELIVERY, classify_connectivity_error(exc)
        )
    return build_connectivity_result(
        ServiceEnum.DELIVERY, ConnectivityStatusEnum.REACHABLE
    )


@router.post("/")
async def check_connectivity(
    body: ConnectivityCheckRequest,
    pmm_api: PMMAPIDep,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> list[ConnectivityResult]:
    """Probe the requested external / inter-service endpoints and report status.

    Probe only the services named in ``body.targets``, running the selected
    probes concurrently. Each is isolated: one endpoint's failure is classified
    independently and never fails the whole response, which always returns
    ``200`` with one entry per requested service, in request order. Tasks and
    Nomad share a single ``/hosts/`` probe, so requesting either (or both) runs
    it once.

    :param body: The request naming which services to probe.
    :param pmm_api: The PMM client dependency, or ``None`` when unconfigured.
    :param inventory_api: The authenticated Inventory API client.
    :param tasks_api: The authenticated Tasks API client.
    :return: One normalized connectivity result per requested service.
    """
    # Preserve request order while collapsing duplicates.
    targets = list(dict.fromkeys(body.targets))
    want_tasks = ServiceEnum.TASKS in targets
    want_nomad = ServiceEnum.NOMAD in targets

    # Register each requested probe as a (service, coroutine) pair. Tasks/Nomad
    # share one coroutine, so it is registered once under a sentinel key.
    probes: dict[str, object] = {}
    if ServiceEnum.PMM in targets:
        probes[ServiceEnum.PMM] = _probe_pmm(pmm_api)
    if ServiceEnum.INVENTORY in targets:
        probes[ServiceEnum.INVENTORY] = inventory_api.check_connectivity(
            ServiceEnum.INVENTORY, path=_INVENTORY_PROBE_PATH
        )
    if want_tasks or want_nomad:
        probes["_tasks_nomad"] = _probe_tasks_and_nomad(tasks_api)
    if ServiceEnum.DELIVERY in targets:
        probes[ServiceEnum.DELIVERY] = _probe_delivery()

    completed = dict(zip(probes, await asyncio.gather(*probes.values()), strict=False))

    # Expand the shared Tasks/Nomad result into the requested halves.
    by_service: dict[str, ConnectivityResult] = {}
    for key, result in completed.items():
        if key == "_tasks_nomad":
            tasks_result, nomad_result = result
            if want_tasks:
                by_service[ServiceEnum.TASKS] = tasks_result
            if want_nomad:
                by_service[ServiceEnum.NOMAD] = nomad_result
        else:
            by_service[key] = result

    return [by_service[service] for service in targets]
