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

"""Define the ``/api/sep/hosts/`` JSON endpoint exposing executor targets.

Mirror the executor-host data already used to render Jinja templates so the
React frontend can populate its host selector through SEP rather than calling
the Tasks and Inventory APIs directly.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.exceptions import HTTPBadGatewayException
from app.core.pagination import fetch_all_dict_items
from app.sep.api.host_resolution import address_to_name_index
from app.sep.api.openapi import UPSTREAM_TASKS_502_RESPONSE
from app.sep.deps import InventoryAPI, TaskAPI

router = APIRouter()


class HostResponse(BaseModel):
    """Represent a single executor target enriched with an inventory display name.

    :param id: The executor (Nomad / Celery) node name. This is the value
        consumed by dispatch payloads as ``executor_host``.
    :param name: Human-readable label sourced from inventory when available;
        falls back to ``id`` if the host has no inventory match.
    :param address: The network address reported by the executor.
    :param can_elevate: Whether the host can run privileged work: ``True`` able,
        ``False`` measured unable, ``None`` never observed. ``None`` is
        permanent, not transient, for an executor host with no inventory match.
    """

    id: str
    name: str
    address: str
    can_elevate: bool | None = None


def _capabilities_by_executor(
    nodes: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    executor_hosts: dict[str, str],
) -> dict[str, bool | None]:
    """Index each node's measured elevation capability by the executor that measured it.

    Mirrors the name-then-address precedence
    :meth:`~app.sep.sync.models.BaseTaskSyncer.get_task_target` applies when choosing
    the host to probe, so a measurement is published on the executor it was collected
    from. Joining by address alone publishes one executor's measurement on another
    whenever an inventory node's name matches one executor and its address another.

    Each node contributes to exactly one pass: ``get_task_target`` returns on the name
    match, so a node resolved by name never reaches the address rule, and no node can
    publish its measurement on two executors at once.

    :param nodes: Every inventory node row.
    :param observations: Every host observation summary.
    :param executor_hosts: Executor node name to address, as the Tasks API returns it.
    :return: Executor node name to its measured capability, absent when unmeasured.
    :raises KeyError: If an upstream row omits a field the join reads, which the
        caller treats as an inventory outage and degrades on.
    """
    by_node = {
        observation["node_id"]: observation["can_elevate"]
        for observation in observations
    }
    capabilities: dict[str, bool | None] = {}
    unmatched = []
    for node in nodes:
        if node["name"] in executor_hosts:
            capabilities.setdefault(node["name"], by_node.get(node["id"]))
        else:
            unmatched.append(node)
    executors_by_address = address_to_name_index(executor_hosts.items())
    for node in unmatched:
        target = executors_by_address.get(node["address"])
        if target is not None and target not in capabilities:
            capabilities[target] = by_node.get(node["id"])
    return capabilities


@router.get(
    "/",
    responses=UPSTREAM_TASKS_502_RESPONSE,
)
async def list_hosts(
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> list[HostResponse]:
    """Return executor hosts merged with inventory display names.

    Call ``tasks_api.get('/hosts/')`` for executor targets and the Inventory
    API for display-name enrichment. The two upstream calls degrade
    differently: Inventory failures cause hosts without a match to keep the
    raw executor node name (the response still returns ``200``), but a
    Tasks-API failure (HTTP or connection error) is re-raised as
    :class:`~app.core.exceptions.HTTPBadGatewayException` so the SEP exception
    handler emits a ``502`` JSON body ``{"detail": "<upstream detail>"}`` that
    the React frontend surfaces through its React Query error slot.

    The display name and the elevation capability are joined on **different
    keys** — address and executor name respectively — and may resolve to
    different inventory nodes. They answer different questions: the display name
    asks what inventory calls this address, the capability asks which executor
    was measured. Collapsing them into one index misattributes the measurement.

    :param tasks_api: The Tasks API client used to fetch executor hosts.
    :param inventory_api: The Inventory API client used to enrich the hosts
        with their display names and measured capabilities.
    :return: Sorted list of hosts, each with executor id, friendly name,
        network address, and elevation capability.
    :raises HTTPBadGatewayException: If the Tasks API call fails with an
        ``HTTPException`` (e.g. an upstream non-2xx response) or an
        ``OSError`` (e.g. a connection failure).
    """
    try:
        executor_hosts = await tasks_api.get("/hosts/")
    except (HTTPException, OSError) as exc:
        detail = getattr(exc, "detail", str(exc))
        raise HTTPBadGatewayException(detail=str(detail)) from exc

    try:
        nodes = await fetch_all_dict_items(
            lambda pagination: inventory_api.get(
                "/nodes/", params=pagination.model_dump()
            )
        )
        observations = await fetch_all_dict_items(
            lambda pagination: inventory_api.get(
                "/nodes/system-observations", params=pagination.model_dump()
            )
        )
        display_names = address_to_name_index(
            (node["name"], node["address"]) for node in nodes
        )
        capabilities = _capabilities_by_executor(nodes, observations, executor_hosts)
    except (HTTPException, TypeError, KeyError, OSError):
        display_names = {}
        capabilities = {}

    return sorted(
        [
            HostResponse(
                id=node_name,
                name=display_names.get(address, node_name),
                address=address,
                can_elevate=capabilities.get(node_name),
            )
            for node_name, address in executor_hosts.items()
        ],
        key=lambda host: host.name.casefold(),
    )
