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
    :type id: str
    :param name: Human-readable label sourced from inventory when available;
        falls back to ``id`` if the host has no inventory match.
    :type name: str
    :param address: The network address reported by the executor.
    :type address: str
    """

    id: str
    name: str
    address: str


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

    :param tasks_api: The Tasks API client used to fetch executor hosts.
    :type tasks_api: TaskAPI
    :param inventory_api: The Inventory API client used to enrich the hosts
        with their display names.
    :type inventory_api: InventoryAPI
    :return: Sorted list of hosts, each with executor id, friendly name,
        and network address.
    :rtype: list[HostResponse]
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
        display_names = address_to_name_index(
            (node["name"], node["address"]) for node in nodes
        )
    except (HTTPException, TypeError, KeyError, OSError):
        display_names = {}

    return sorted(
        [
            HostResponse(
                id=node_name,
                name=display_names.get(address, node_name),
                address=address,
            )
            for node_name, address in executor_hosts.items()
        ],
        key=lambda host: host.name.casefold(),
    )
