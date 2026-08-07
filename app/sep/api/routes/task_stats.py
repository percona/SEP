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

"""Define the ``/api/sep/task-stats/{task_name}`` JSON endpoint proxying task statistics.

Expose the Tasks-service ``GET /stats/{task}`` aggregation through the SEP
gateway so the React frontend (``useTaskStats``) does not bypass the SEP
``/api/*`` routing layer when fetching per-task execution stats.
"""

from fastapi import APIRouter, HTTPException

from app.core.exceptions import HTTPBadGatewayException
from app.core.utils.fields import ArbitraryMapping
from app.sep.api.openapi import UPSTREAM_TASKS_502_RESPONSE
from app.sep.deps import TaskAPI

router = APIRouter()


@router.get(
    "/{task_name}",
    responses=UPSTREAM_TASKS_502_RESPONSE,
)
async def get_task_stats(
    task_name: str,
    tasks_api: TaskAPI,
) -> ArbitraryMapping:
    """Return aggregated execution statistics for ``task_name``.

    Proxy to the Tasks-service ``GET /stats/{task_name}`` aggregation so the
    React frontend reaches the data through SEP rather than calling the Tasks
    sub-app directly. On upstream failure, re-raise as
    :class:`~app.core.exceptions.HTTPBadGatewayException` so the SEP exception
    handler emits a ``502`` JSON body ``{"detail": "<upstream detail>"}`` that
    the React frontend surfaces through React Query's error state.

    :param task_name: The task name (not the database id) whose stats are
        being requested.
    :type task_name: str
    :param tasks_api: The Tasks API client used to fetch the upstream stats.
    :type tasks_api: TaskAPI
    :return: The raw upstream stats payload.
    :rtype: dict[str, Any]
    :raises HTTPBadGatewayException: If the Tasks API call fails with an
        ``HTTPException`` (e.g. an upstream non-2xx response) or an
        ``OSError`` (e.g. a connection failure).
    """
    try:
        return await tasks_api.get(f"/stats/{task_name}")
    except (HTTPException, OSError) as exc:
        detail = getattr(exc, "detail", str(exc))
        raise HTTPBadGatewayException(detail=str(detail)) from exc
