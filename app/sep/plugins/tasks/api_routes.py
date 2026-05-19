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

Mounted at ``/api/plugins/tasks/`` via ``plugins_router`` in
``app/sep/api/router.py``. List and detail handlers proxy the tasks HTTP API
through ``TaskAPI``, mirroring the legacy Jinja routes in
``app.sep.plugins.tasks.routes``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.sep.deps import ExecutorHostsCtx, IsApiAuthenticated, TaskAPI
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.tasks.deps import TaskDep
from app.sep.plugins.tasks.models import (
    ExecutorHostMetadata,
    PeriodicTaskSummary,
    TaskDetailResponse,
    TaskListResponse,
)
from app.sep.plugins.tasks.schema import TASKS_PLUGIN_SCHEMA
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum

router = APIRouter()
schema_endpoint(router=router, plugin_schema=TASKS_PLUGIN_SCHEMA)


def iso_or_none(value: Any) -> str | None:
    """Return an ISO 8601 string for datetimes, or pass through strings unchanged.

    :param value: A datetime, ISO string, or ``None``.
    :type value: Any
    :return: The serialized timestamp, or ``None``.
    :rtype: str | None
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def build_periodic_summary(item: dict[str, Any]) -> PeriodicTaskSummary:
    """Map a tasks-API periodic-task dict to the plugin summary model.

    :param item: One periodic task from ``GET /{task_name}/periodic/``.
    :type item: dict[str, Any]
    :return: The read-only periodic summary for the detail bundle.
    :rtype: PeriodicTaskSummary
    """
    execute_request = item.get("execute_request") or {}
    chain_task_names = execute_request.get("chain_task_names") or []
    return PeriodicTaskSummary(
        id=item["id"],
        name=item["name"],
        enabled=item["enabled"],
        period=item.get("period"),
        next_run_at=iso_or_none(item.get("next_run_at")),
        last_run_at=iso_or_none(item.get("last_run_at")),
        total_run_count=item.get("total_run_count"),
        chain_task_names=chain_task_names,
    )


@router.get(
    "/", dependencies=[IsApiAuthenticated], response_model=list[TaskListResponse]
)
async def tasks_api_list(tasks_api: TaskAPI) -> list[TaskListResponse]:
    """List task definitions for the read-only plugin UI.

    :param tasks_api: Async client for the tasks sub-app.
    :type tasks_api: TaskAPI
    :return: Task rows for the schema-driven list view.
    :rtype: list[TaskListResponse]
    """
    response = await tasks_api.get("/")
    return [
        TaskListResponse(
            name=item["name"],
            backend=TaskBackendEnum(item["backend"]),
            created_at=iso_or_none(item.get("created_at")),
            created_by=item.get("created_by"),
            last_updated_by=item.get("last_updated_by"),
        )
        for item in response["items"]
    ]


@router.get(
    "/{task_name}",
    dependencies=[IsApiAuthenticated],
    response_model=TaskDetailResponse,
)
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
    :return: Task definition, running rows, history, periodic schedules, and
        executor hosts.
    :rtype: TaskDetailResponse
    """
    running_tasks: list[dict[str, Any]] = []
    execution_history: dict[str, Any] = {"items": []}
    periodic_summary: list[PeriodicTaskSummary] = []

    if not task.is_template:
        periodic_response = await tasks_api.get(f"/{task.name}/periodic/")
        periodic_summary = [build_periodic_summary(item) for item in periodic_response]
        execution_history = await tasks_api.get(f"/{task.name}/history/")
        running_response = await tasks_api.get(
            f"/{task.name}/history/",
            params={"status": TaskHistoryStatusEnum.RUNNING},
        )
        running_tasks = running_response["items"]

    executor_hosts = [
        ExecutorHostMetadata(value=host["value"], label=host["label"])
        for host in executor_hosts_ctx.as_template_list()
    ]

    return TaskDetailResponse(
        task=task.model_dump(mode="json"),
        running_tasks=running_tasks,
        execution_history=execution_history,
        periodic_summary=periodic_summary,
        executor_hosts=executor_hosts,
    )
