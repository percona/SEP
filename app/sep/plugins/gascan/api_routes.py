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

"""Define the JSON API router for the Gascan plugin.

Mounted at ``/api/plugins/gascan/`` via ``plugins_router`` in
``app/sep/api/router.py``.
"""

import logging

from fastapi import APIRouter
from fastapi import status as http_status

from app.sep.deps import TaskAPI
from app.sep.plugins.gascan.deps import (
    build_gascan_api_task_response,
    build_gascan_task,
    GascanTask,
    get_gascan_api_task_responses,
    get_gascan_task,
    get_gascan_task_status,
)
from app.sep.plugins.gascan.models import GascanTaskResponse, GascanTaskWrite
from app.sep.plugins.gascan.schema import gascan_schema
from app.sep.plugins.framework.api import schema_endpoint
from app.tasks.models import Task, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=gascan_schema)


@router.get("/", response_model=list[GascanTaskResponse])
async def gascan_api_list(
    tasks_api: TaskAPI,
    status: TaskHistoryStatusEnum | None = None,
) -> list[GascanTaskResponse]:
    """List gascan tasks."""
    return await get_gascan_api_task_responses(
        tasks_api,
        status=status,
    )


@router.get("/{task_name}", response_model=GascanTaskResponse)
async def gascan_api_detail(
    task_name: str,
    tasks_api: TaskAPI,
) -> GascanTaskResponse:
    """Retrieve a single gascan task."""
    task = await get_gascan_task(task_name, tasks_api)
    task_status = await get_gascan_task_status(task.name, tasks_api)
    return build_gascan_api_task_response(task, status=task_status)


@router.post(
    "/",
    response_model=GascanTaskResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def gascan_api_create(
    body: GascanTaskWrite,
    tasks_api: TaskAPI,
) -> GascanTaskResponse:
    """Create a gascan task from a JSON payload request body."""
    logger.debug("Create gascan task (JSON path): %s", body.task_name)
    task_write = build_gascan_task(body)
    created = await tasks_api.post("/", json=task_write.model_dump())
    task = Task.model_validate(created)
    return build_gascan_api_task_response(task, status=None)


@router.delete("/{task_name}", status_code=http_status.HTTP_204_NO_CONTENT)
async def gascan_api_delete(
    task: GascanTask,
    tasks_api: TaskAPI,
) -> None:
    """Delete a gascan task."""
    await tasks_api.delete(f"/{task.name}")
