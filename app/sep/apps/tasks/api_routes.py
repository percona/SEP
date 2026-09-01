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

"""Define the read-only JSON API router for the Tasks plugin.

Mounted at ``/api/apps/tasks/`` via ``apps_router`` in
``app/sep/api/router.py``. List and detail handlers proxy the tasks HTTP API
through ``TaskAPI``, mirroring the legacy Jinja routes in
``app.sep.apps.tasks.routes``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.pagination import build_proxied_page, PaginatedResponse, PaginationDep
from app.core.requests import as_json_array, as_json_object
from app.sep.apps.framework.api import schema_endpoint
from app.sep.apps.tasks.deps import TaskDep
from app.sep.apps.tasks.models import (
    ExecutorHostMetadata,
    PeriodicTaskSummary,
    TaskDetailResponse,
    TaskListResponse,
)
from app.sep.apps.tasks.schema import TASKS_PLUGIN_SCHEMA
from app.sep.deps import (
    ExecutorHostsCtx,
    get_username_mapping,
    TaskAPI,
)
from app.tasks.models import TaskBackendEnum, TaskResponse

router = APIRouter(tags=["Task Manager"])
schema_endpoint(router=router, plugin_schema=TASKS_PLUGIN_SCHEMA)


@router.get("/")
async def tasks_api_list(
    tasks_api: TaskAPI, pagination: PaginationDep
) -> PaginatedResponse[TaskListResponse]:
    """List task definitions for the read-only plugin UI.

    :param tasks_api: Async client for the tasks sub-app.
    :param pagination: Validated offset/limit forwarded to the upstream Tasks API.
    :return: A paginated envelope of task rows for the schema-driven list view.
    """
    response = as_json_object(
        await tasks_api.get(
            "/", params={"offset": pagination.offset, "limit": pagination.limit}
        )
    )
    user_id_to_username = await get_username_mapping()
    items = [
        TaskListResponse(
            name=item["name"],
            backend=TaskBackendEnum(item["backend"]),
            created_at=item.get("created_at"),
            created_by=user_id_to_username.get(
                item.get("created_by"), item.get("created_by")
            ),
            last_updated_by=user_id_to_username.get(
                item.get("last_updated_by"), item.get("last_updated_by")
            ),
        )
        for item in response["items"]
    ]
    return build_proxied_page(items, response, pagination, client_side_filtered=False)


@router.get("/{task_name}")
async def tasks_api_detail(
    task: TaskDep,
    tasks_api: TaskAPI,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> TaskDetailResponse:
    """Return the per-task detail bundle for the read-only plugin UI.

    :param task: The task definition resolved by name.
    :type task: Task
    :param tasks_api: Async client for the tasks sub-app.
    :type tasks_api: TaskAPI
    :param executor_hosts_ctx: Executor hosts enriched with inventory labels.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: Task definition, history, periodic schedules, and executor hosts.
    :rtype: TaskDetailResponse
    """
    execution_history: dict[str, object] = {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 0,
    }
    periodic_summary: list[PeriodicTaskSummary] = []

    if not task.is_template:
        periodic_response = as_json_array(
            await tasks_api.get(f"/{task.name}/periodic/")
        )
        periodic_summary = [
            PeriodicTaskSummary.model_validate(item) for item in periodic_response
        ]
        execution_history = as_json_object(
            await tasks_api.get(f"/{task.name}/history/")
        )

    executor_hosts = [
        ExecutorHostMetadata(value=host["value"], label=host["label"])
        for host in executor_hosts_ctx.as_template_list()
    ]

    return TaskDetailResponse(
        task=TaskResponse.model_validate(task.model_dump(mode="json")),
        execution_history=execution_history,
        periodic_summary=periodic_summary,
        executor_hosts=executor_hosts,
    )
