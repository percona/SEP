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

"""Define the JSON API router for the backup_mongo restores plugin.

Mounted at ``/api/plugins/backup_mongo/restores/`` via
``include_router`` on the backup_mongo ``api_routes`` router. Authentication is
enforced at the ``api_router`` level; ``schema_endpoint`` pins
``IsApiAuthenticated`` per route for safety.
"""

import logging

from fastapi import APIRouter
from fastapi import status as http_status

from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.sep.deps import (
    HasNoConflictedRunningTasks,
    InventoryAPI,
    TaskAPI,
)
from app.sep.plugins.backup_mongo.restore.deps import (
    build_restore_mongo_api_detail_response,
    build_restore_mongo_api_task_response,
    create_restore_task_group,
    delete_restore_task_group,
    get_restore_mongo_api_task_responses,
    get_restores_task,
    RestoreParentTask,
    RestoresTask,
    RestoreTaskGroupFromBody,
    RestoreUpdateFormFromBody,
    UnprotectedRestoreParentTask,
    update_restore_task_group,
)
from app.sep.plugins.backup_mongo.restore.models import (
    RestoreExecuteWrite,
    RestoreExecutionResponse,
    RestoreTaskDetailResponse,
    RestoreTaskResponse,
)
from app.sep.plugins.backup_mongo.restore.schema import restore_mongo_schema
from app.sep.plugins.framework import get_task_latest_status
from app.sep.plugins.framework.api import derive_execute_route, schema_endpoint
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=restore_mongo_schema)


@router.get("/")
async def restore_mongo_api_list(
    tasks_api: TaskAPI,
    pagination: PaginationDep,
    status: TaskHistoryStatusEnum | None = None,
) -> PaginatedResponse[RestoreTaskResponse]:
    """List parent PBM restore config tasks."""
    return await get_restore_mongo_api_task_responses(
        tasks_api,
        pagination=pagination,
        status=status,
    )


@router.get("/{task_name}")
async def restore_mongo_api_detail(
    parent_task: RestoreParentTask,
    tasks_api: TaskAPI,
) -> RestoreTaskDetailResponse:
    """Retrieve a single parent restore task with child task status."""
    return await build_restore_mongo_api_detail_response(parent_task, tasks_api)


@router.post(
    "/",
    status_code=http_status.HTTP_201_CREATED,
)
async def restore_mongo_api_create(
    payloads: RestoreTaskGroupFromBody,
    tasks_api: TaskAPI,
) -> RestoreTaskDetailResponse:
    """Create a restore task group from a JSON payload request body.

    POSTs the parent config task, restore leg, pbm-list helper, and optional
    force-resync child for physical restores. Rolls back on any failure.
    """
    logger.debug(
        "Create backup_mongo restore task group (JSON path): %s",
        payloads.config_task.name,
    )
    await create_restore_task_group(
        tasks_api,
        payloads.config_task,
        payloads.restore_task,
        payloads.pbm_list_task,
        payloads.force_resync_task,
    )
    task = await get_restores_task(payloads.config_task.name, tasks_api)
    return await build_restore_mongo_api_detail_response(task, tasks_api)


@router.put(
    "/{task_name}",
    dependencies=[HasNoConflictedRunningTasks],
)
async def restore_mongo_api_update(
    parent_task: UnprotectedRestoreParentTask,
    form: RestoreUpdateFormFromBody,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> RestoreTaskResponse:
    """Update a restore task from a JSON payload request body.

    PUTs the parent config payload to the config task name and refreshes each
    child leg (restore, pbm-list, optional force-resync) in place.
    """
    logger.debug("Update backup_mongo restore task (JSON path): %s", parent_task.name)
    updated_task = await update_restore_task_group(
        tasks_api,
        parent_task,
        form,
        inventory_api,
    )
    task_status = await get_task_latest_status(tasks_api, updated_task.name)
    return build_restore_mongo_api_task_response(updated_task, status=task_status)


derive_execute_route(
    router,
    name="restore_mongo_api_execute",
    description="Execute a restore task.",
    task_dep=RestoresTask,
    write_model=RestoreExecuteWrite,
    response_model=RestoreExecutionResponse,
)


@router.delete("/{task_name}", status_code=http_status.HTTP_204_NO_CONTENT)
async def restore_mongo_api_delete(
    parent_task: RestoreParentTask,
    tasks_api: TaskAPI,
) -> None:
    """Delete a restore task group."""
    await delete_restore_task_group(tasks_api, parent_task)
