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

from fastapi import APIRouter
from pydantic import BaseModel

from app.sep.deps import ExecutorHostsCtx

router = APIRouter()


class HostResponse(BaseModel):
    """Single executor target enriched with an inventory display name.

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
async def list_hosts(executor_hosts_ctx: ExecutorHostsCtx) -> list[HostResponse]:
    """Return executor hosts merged with inventory display names.

    Internally call ``tasks_api.get('/hosts/')`` (executor targets) and the
    Inventory API (display-name lookup) via the shared
    :func:`app.sep.deps.get_executor_hosts_context` dep. Inventory failures
    degrade gracefully — hosts without an inventory match keep the raw
    executor node name. Tasks-API failures also degrade gracefully (handled
    by ``get_executor_hosts``); the route returns an empty list when the
    Tasks API is unreachable rather than surfacing an upstream error.

    :param executor_hosts_ctx: Executor host context with display name lookup.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: Sorted list of hosts, each with executor id, friendly name, and
        network address.
    :rtype: list[HostResponse]
    """
    return sorted(
        [
            HostResponse(
                id=node_name,
                name=executor_hosts_ctx.display_name(node_name),
                address=address,
            )
            for node_name, address in executor_hosts_ctx.hosts.items()
        ],
        key=lambda host: host.name.casefold(),
    )
