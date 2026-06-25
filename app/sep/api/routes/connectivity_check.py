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

Expose a single generic ``POST`` that probes each configured external /
inter-service endpoint (PMM, Inventory, Tasks, Nomad) on demand and reports
normalized per-endpoint connectivity status, so an admin can confirm an
endpoint or credential change is reachable and valid before relying on it.

The probes are driven by the overridable ``RemoteAPI.check_connectivity``
capability and fan out concurrently. A failure for one endpoint is captured and
classified independently, so a single outage never fails the whole response.
PMM, Inventory, and Tasks are built through the existing
``settings.get_remote_api`` / ``ClientRegistry`` path (honoring SSL config and
hot-reloaded overrides); Nomad reuses the Tasks ``/hosts/`` proxy -- a healthy
response proves both Tasks and Nomad are reachable, so no new Tasks-app endpoint
is added.
"""

import asyncio

from fastapi import APIRouter, HTTPException, status

from app.core.requests.connectivity import (
    build_connectivity_result,
    classify_connectivity_error,
    ConnectivityResult,
    ConnectivityStatusEnum,
    PROBE_TIMEOUT_SECONDS,
)
from app.sep.deps import InventoryAPI, TaskAPI
from app.sep.plugins.alerts.deps import PMMAPIDep

router = APIRouter()

#: Stable service identifiers returned in each result's ``service`` field.
SERVICE_PMM = "pmm"
SERVICE_INVENTORY = "inventory"
SERVICE_TASKS = "tasks"
SERVICE_NOMAD = "nomad"

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
    :type pmm_api: PMMAPIDep
    :return: The PMM connectivity result.
    :rtype: ConnectivityResult
    """
    if pmm_api is None:
        return build_connectivity_result(
            SERVICE_PMM,
            ConnectivityStatusEnum.UNREACHABLE,
            detail="PMM is not configured.",
        )
    return await pmm_api.check_connectivity(SERVICE_PMM)


async def _probe_tasks_and_nomad(
    tasks_api: TaskAPI,
) -> tuple[ConnectivityResult, ConnectivityResult]:
    """Derive both Tasks and Nomad results from a single ``/hosts/`` probe.

    A ``200`` (including an empty cluster) means both are reachable. Only an
    upstream ``502 Bad Gateway`` -- the Tasks proxy answered but its executor
    backend is unreachable -- means Tasks is reachable while Nomad is not. Any
    other failure (other HTTP errors such as a ``500`` indicating an unhealthy
    Tasks API itself, plus connection-level / SSL / timeout / auth failures)
    applies to both, since a healthy Tasks API cannot be confirmed and Nomad
    therefore cannot be either.

    :param tasks_api: The authenticated Tasks API client.
    :type tasks_api: TaskAPI
    :return: A ``(tasks_result, nomad_result)`` pair.
    :rtype: tuple[ConnectivityResult, ConnectivityResult]
    """
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await tasks_api.get(_HOSTS_PROBE_PATH)
    except Exception as exc:  # noqa: BLE001 -- classified, never re-raised
        if (
            isinstance(exc, HTTPException)
            and exc.status_code == status.HTTP_502_BAD_GATEWAY
        ):
            # The Tasks proxy answered but its executor backend is down, so
            # Tasks is reachable but Nomad is not.
            return (
                build_connectivity_result(
                    SERVICE_TASKS, ConnectivityStatusEnum.REACHABLE
                ),
                build_connectivity_result(
                    SERVICE_NOMAD,
                    ConnectivityStatusEnum.UNREACHABLE,
                    detail="Executor backend unreachable.",
                ),
            )
        # The Tasks endpoint itself failed (HTTP 5xx other than 502, connection,
        # SSL, timeout, or auth); Nomad cannot be confirmed either.
        probe_status = classify_connectivity_error(exc)
        return (
            build_connectivity_result(SERVICE_TASKS, probe_status),
            build_connectivity_result(SERVICE_NOMAD, probe_status),
        )
    return (
        build_connectivity_result(SERVICE_TASKS, ConnectivityStatusEnum.REACHABLE),
        build_connectivity_result(SERVICE_NOMAD, ConnectivityStatusEnum.REACHABLE),
    )


@router.post("/")
async def check_connectivity(
    pmm_api: PMMAPIDep,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> list[ConnectivityResult]:
    """Probe every configured external / inter-service endpoint and report status.

    Run the PMM, Inventory, and Tasks/Nomad probes concurrently. Each is
    isolated: one endpoint's failure is classified independently and never fails
    the whole response, which always returns ``200`` with one entry per service
    (``pmm``, ``inventory``, ``tasks``, ``nomad``).

    :param pmm_api: The PMM client dependency, or ``None`` when unconfigured.
    :type pmm_api: PMMAPIDep
    :param inventory_api: The authenticated Inventory API client.
    :type inventory_api: InventoryAPI
    :param tasks_api: The authenticated Tasks API client.
    :type tasks_api: TaskAPI
    :return: One normalized connectivity result per service.
    :rtype: list[ConnectivityResult]
    """
    pmm_result, inventory_result, tasks_nomad = await asyncio.gather(
        _probe_pmm(pmm_api),
        inventory_api.check_connectivity(SERVICE_INVENTORY, path=_INVENTORY_PROBE_PATH),
        _probe_tasks_and_nomad(tasks_api),
    )
    tasks_result, nomad_result = tasks_nomad
    return [pmm_result, inventory_result, tasks_result, nomad_result]
