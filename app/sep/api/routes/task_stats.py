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

"""Define the ``/api/sep/task-stats/`` JSON endpoint proxying task statistics.

Expose the Tasks-service ``GET /stats/{task}`` aggregation through the SEP
gateway so the React frontend (``useTaskStats``) does not bypass the SEP
``/api/*`` routing layer when fetching per-task execution stats.
"""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.sep.deps import TaskAPI

router = APIRouter()

UPSTREAM_ERROR_HEADER = "X-Sep-Upstream-Error"


class TaskStatsDuration(BaseModel):
    """Represent aggregated duration metrics for a task.

    :param average_seconds: Mean duration across recorded executions, or
        ``None`` if no executions have completed.
    :type average_seconds: float | None
    :param last_seconds: Duration of the most recent finished execution.
    :type last_seconds: float | None
    :param total_seconds: Sum of all recorded execution durations.
    :type total_seconds: float | None
    """

    average_seconds: float | None = None
    last_seconds: float | None = None
    total_seconds: float | None = None


class TaskStatsStatus(BaseModel):
    """Represent pass/fail counts for a task across its history.

    :param pass_: Number of successful executions. Serialized as ``pass``.
    :type pass_: int
    :param fail: Number of failed executions.
    :type fail: int
    """

    pass_: int = Field(default=0, alias="pass")
    fail: int = 0

    model_config = {"populate_by_name": True}


class TaskStatsResponse(BaseModel):
    """Represent the wire-shape mirror of ``app.tasks.models.TaskStats`` for the SEP proxy.

    Mirror only the JSON surface (computed fields plus ``engine``) so the
    OpenAPI schema can be tightened independently of the upstream model.
    The upstream ``tasks`` list is excluded from serialization on the Tasks
    side and is not part of this contract.

    :param engine: Execution backend identifier (e.g. ``nomad``).
    :type engine: str
    :param total: Total number of recorded executions for the task.
    :type total: int
    :param status: Pass/fail summary across executions.
    :type status: TaskStatsStatus
    :param duration: Aggregated duration metrics.
    :type duration: TaskStatsDuration
    :param last_finished_at: ISO timestamp of the most recent finished
        execution, or ``None`` when no execution has completed.
    :type last_finished_at: str | None
    """

    engine: str = "nomad"
    total: int = 0
    status: TaskStatsStatus = Field(default_factory=TaskStatsStatus)
    duration: TaskStatsDuration = Field(default_factory=TaskStatsDuration)
    last_finished_at: str | None = None


@router.get("/{task_name}", response_model=TaskStatsResponse)
async def get_task_stats(
    task_name: str,
    response: Response,
    tasks_api: TaskAPI,
) -> TaskStatsResponse:
    """Return aggregated execution statistics for ``task_name``.

    Proxy to the Tasks-service ``GET /stats/{task_name}`` aggregation so the
    React frontend reaches the data through SEP rather than calling the Tasks
    sub-app directly. Degrade gracefully on upstream failure: catch
    ``HTTPException`` / ``OSError``, attach the ``X-Sep-Upstream-Error``
    response header so the React shell can surface a notification, and return
    a default-shaped empty payload so the stats card can render an empty
    state without a hard error.

    :param task_name: The task name (not the database id) whose stats are
        being requested.
    :type task_name: str
    :param response: The outgoing response, used to attach the upstream
        error header on Tasks-API failure.
    :type response: Response
    :param tasks_api: The Tasks API client used to fetch the upstream stats.
    :type tasks_api: TaskAPI
    :return: The aggregated stats payload, or an empty default when the
        upstream call fails.
    :rtype: TaskStatsResponse
    """
    try:
        payload = await tasks_api.get(f"/stats/{task_name}")
    except (HTTPException, OSError) as exc:
        detail = getattr(exc, "detail", str(exc))
        response.headers[UPSTREAM_ERROR_HEADER] = str(detail)
        return TaskStatsResponse()
    return TaskStatsResponse.model_validate(payload)
