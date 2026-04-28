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

"""Define the JSON API router for the Checksums plugin.

Mounted at ``/api/plugins/checksums/`` via ``plugins_router`` in
``app/sep/api/router.py``. Authentication is enforced at the ``api_router``
level; the ``schema_endpoint`` helper also pins ``IsApiAuthenticated`` per
route for safety.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi import status as http_status

from app.inventory.models import ServiceTypeEnum
from app.sep.deps import InventoryAPI, TaskAPI
from app.sep.plugins.checksums.deps import (
    build_checksum_task,
    build_checksums_api_task_response,
    ChecksumsTask,
    get_checksums_api_task_responses,
    get_checksums_task,
    get_checksums_task_status,
)
from app.sep.plugins.checksums.models import ChecksumTaskResponse, ChecksumTaskWrite
from app.sep.plugins.checksums.schema import checksums_schema
from app.sep.plugins.framework import maybe_record_connectivity_warning
from app.sep.plugins.framework.api import schema_endpoint
from app.tasks.models import Task, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=checksums_schema)


@router.get("/", response_model=list[ChecksumTaskResponse])
async def checksums_api_list(
    tasks_api: TaskAPI,
    service_type: ServiceTypeEnum | None = None,
    status: TaskHistoryStatusEnum | None = None,
) -> list[ChecksumTaskResponse]:
    """List checksum tasks."""
    return await get_checksums_api_task_responses(
        tasks_api,
        service_type=service_type,
        status=status,
    )


@router.get("/{task_name}", response_model=ChecksumTaskResponse)
async def checksums_api_detail(
    task_name: str,
    tasks_api: TaskAPI,
) -> ChecksumTaskResponse:
    """Retrieve a single checksum task."""
    task = await get_checksums_task(task_name, tasks_api)
    task_status = await get_checksums_task_status(task.name, tasks_api)
    return build_checksums_api_task_response(task, status=task_status)


@router.post(
    "/",
    response_model=ChecksumTaskResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def checksums_api_create(
    body: ChecksumTaskWrite,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
    *,
    check_connectivity: Annotated[bool, Query()] = True,
) -> ChecksumTaskResponse:
    """Create a checksum task from a JSON payload request body.

    :param check_connectivity: Whether to verify the target database is
        reachable after task creation. Mirrors the form flow's
        ``check_connectivity`` checkbox semantic.
    :type check_connectivity: bool
    """
    logger.debug("Create checksums task (JSON path): %s", body.task_name)
    task_write = await build_checksum_task(body, inventory_api)
    created = await tasks_api.post("/", json=task_write.model_dump())
    task = Task.model_validate(created)
    connectivity_warning = await maybe_record_connectivity_warning(
        tasks_api,
        task.data.get("meta", {}),
        check_connectivity=check_connectivity,
    )
    return build_checksums_api_task_response(
        task,
        status=None,
        connectivity_warning=connectivity_warning,
    )


@router.delete("/{task_name}", status_code=http_status.HTTP_204_NO_CONTENT)
async def checksums_api_delete(
    task: ChecksumsTask,
    tasks_api: TaskAPI,
) -> None:
    """Delete a checksum task."""
    await tasks_api.delete(f"/{task.name}")
