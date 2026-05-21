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

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.sep.api.constants import UPSTREAM_ERROR_HEADER
from app.sep.api.host_resolution import address_to_name_index
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


@router.get("/", response_model=list[HostResponse])
async def list_hosts(
    response: Response,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> list[HostResponse]:
    """Return executor hosts merged with inventory display names.

    Call ``tasks_api.get('/hosts/')`` for executor targets and the Inventory
    API for display-name enrichment. Both upstream calls degrade gracefully
    — Inventory failures cause hosts without a match to keep the raw
    executor node name, and Tasks-API failures cause an empty list to be
    returned rather than a hard error. Tasks-API failures (HTTP and
    connection errors alike) additionally set the ``X-Sep-Upstream-Error``
    response header so the frontend can surface the failure detail through
    its notification system without breaking the ``200 []`` response contract
    that lets the dropdown render "No hosts available".

    :param response: The outgoing response, used to attach the upstream
        error header on Tasks-API failure.
    :type response: Response
    :param tasks_api: The Tasks API client used to fetch executor hosts.
    :type tasks_api: TaskAPI
    :param inventory_api: The Inventory API client used to enrich the hosts
        with their display names.
    :type inventory_api: InventoryAPI
    :return: Sorted list of hosts, each with executor id, friendly name,
        and network address.
    :rtype: list[HostResponse]
    """
    try:
        executor_hosts: dict[str, str] = await tasks_api.get("/hosts/")
    except (HTTPException, OSError) as exc:
        detail = getattr(exc, "detail", str(exc))
        response.headers[UPSTREAM_ERROR_HEADER] = str(detail)
        return []

    try:
        inventory_response = await inventory_api.get("/", params={"limit": 0})
        display_names = address_to_name_index(
            (node["name"], node["address"]) for node in inventory_response["items"]
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
