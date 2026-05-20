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

"""Define the ``/api/sep/dashboard/`` JSON endpoint for dashboard statistics.

Returns aggregate counts for the four dashboard stat cards in a single round
trip so the React frontend avoids four parallel upstream calls. Each source
degrades independently — a failure yields ``0`` for that counter and its name
is appended to the ``X-Sep-Upstream-Error`` response header so the frontend
can distinguish real zeroes from degraded counts.
"""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.sep.deps import InventoryAPI, SessionDep, TaskAPI
from app.sep.snippets.crud import SnippetManager

router = APIRouter()

UPSTREAM_ERROR_HEADER = "X-Sep-Upstream-Error"


class DashboardStatsResponse(BaseModel):
    """Represent aggregate counts for the four dashboard stat cards.

    :param nodes: Total inventory node count.
    :type nodes: int
    :param tasks: Total active task count.
    :type tasks: int
    :param snippets: Total snippet count.
    :type snippets: int
    :param targets: Total executor target (host) count.
    :type targets: int
    """

    nodes: int
    tasks: int
    snippets: int
    targets: int


@router.get("/", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    response: Response,
    session: SessionDep,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> DashboardStatsResponse:
    """Return aggregate counts for all four dashboard stat cards.

    Sources (each degrades to ``0`` on failure):

    * ``nodes`` — ``GET /summary/`` on the Inventory API.
    * ``tasks`` — ``GET /`` on the Tasks API (``limit=0``; reads ``total``).
    * ``snippets`` — :meth:`SnippetManager.count` on the SEP database.
    * ``targets`` — ``GET /hosts/`` on the Tasks API; count of returned items.

    When one or more sources fail the names of the failed sources are joined
    with commas and set on the ``X-Sep-Upstream-Error`` response header so the
    caller can surface a partial-failure warning without treating all-zero
    counts as healthy data.

    :param response: The outgoing response used to attach the error header.
    :type response: Response
    :param session: The active database session for snippet queries.
    :type session: AsyncSession
    :param tasks_api: Async client for the Tasks sub-app.
    :type tasks_api: RemoteAPI
    :param inventory_api: Async client for the Inventory sub-app.
    :type inventory_api: RemoteAPI
    :return: Aggregate counts for nodes, tasks, snippets, and targets.
    :rtype: DashboardStatsResponse
    """
    nodes = 0
    tasks = 0
    snippets = 0
    targets = 0
    failed: list[str] = []

    try:
        summary = await inventory_api.get("/summary/")
        nodes = int(summary.get("nodes", 0))  # type: ignore[union-attr]
    except (HTTPException, OSError, AttributeError, KeyError, TypeError, ValueError):
        failed.append("nodes")

    try:
        task_list = await tasks_api.get("/", params={"limit": 0})
        tasks = int(task_list.get("total", 0))  # type: ignore[union-attr]
    except (HTTPException, OSError, AttributeError, KeyError, TypeError, ValueError):
        failed.append("tasks")

    try:
        snippets = await SnippetManager.count(session)
    except Exception:  # noqa: BLE001
        failed.append("snippets")

    try:
        host_list = await tasks_api.get("/hosts/")
        targets = len(host_list)  # type: ignore[arg-type]
    except (HTTPException, OSError, AttributeError, TypeError):
        failed.append("targets")

    if failed:
        response.headers[UPSTREAM_ERROR_HEADER] = ",".join(failed)

    return DashboardStatsResponse(
        nodes=nodes,
        tasks=tasks,
        snippets=snippets,
        targets=targets,
    )
