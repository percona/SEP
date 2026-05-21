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

from typing import Any

from fastapi import APIRouter, HTTPException, Response

from app.sep.api.constants import UPSTREAM_ERROR_HEADER
from app.sep.deps import TaskAPI

router = APIRouter()


@router.get("/{task_name}")
async def get_task_stats(
    task_name: str,
    response: Response,
    tasks_api: TaskAPI,
) -> dict[str, Any]:
    """Return aggregated execution statistics for ``task_name``.

    Proxy to the Tasks-service ``GET /stats/{task_name}`` aggregation so the
    React frontend reaches the data through SEP rather than calling the Tasks
    sub-app directly. Degrade gracefully on upstream failure: catch
    ``HTTPException`` / ``OSError``, attach the ``X-Sep-Upstream-Error``
    response header so the React shell can surface a notification, and return
    an empty dict so the stats card can render its empty state without a hard
    error.

    :param task_name: The task name (not the database id) whose stats are
        being requested.
    :type task_name: str
    :param response: The outgoing response, used to attach the upstream
        error header on Tasks-API failure.
    :type response: Response
    :param tasks_api: The Tasks API client used to fetch the upstream stats.
    :type tasks_api: TaskAPI
    :return: The raw upstream stats payload, or ``{}`` when the upstream call
        fails.
    :rtype: dict[str, Any]
    """
    try:
        return await tasks_api.get(f"/stats/{task_name}")
    except (HTTPException, OSError) as exc:
        detail = getattr(exc, "detail", str(exc))
        response.headers[UPSTREAM_ERROR_HEADER] = str(detail)
        return {}
