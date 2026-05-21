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

"""Define the JSON API router for the backup_mongo plugin.

Mounted at ``/api/plugins/backup_mongo/`` via ``plugins_router`` in
``app/sep/api/router.py``. Authentication is enforced at the ``api_router``
level; the ``schema_endpoint`` helper also pins ``IsApiAuthenticated`` per
route for safety.
"""

import logging

from fastapi import APIRouter
from fastapi import status as http_status

from app.sep.deps import (
    HasNoConflictedRunningTasks,
    InventoryAPI,
    IsApiAuthenticated,
    TaskAPI,
)
from app.sep.plugins.backup_mongo.deps import (
    backup_create_from_write,
    backup_derived_task_names,
    build_backup_mongo_api_detail_response,
    build_backup_task_payload,
    get_backup_mongo_api_task_responses,
    get_backups_task,
    resolve_backup_parent_task_name,
)
from app.sep.plugins.backup_mongo.models import (
    BackupExecuteWrite,
    BackupExecutionResponse,
    BackupTaskDetailResponse,
    BackupTaskResponse,
    BackupTaskWrite,
    BackupType,
)
from app.sep.plugins.backup_mongo.schema import backup_mongo_schema
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.framework.cascade import cascade_create_tasks, cascade_delete_tasks
from app.tasks.models import TaskHistoryResponse, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=backup_mongo_schema)


@router.get("/", response_model=list[BackupTaskResponse])
async def backup_mongo_api_list(
    tasks_api: TaskAPI,
    status: TaskHistoryStatusEnum | None = None,
) -> list[BackupTaskResponse]:
    """List parent PBM backup config tasks."""
    return await get_backup_mongo_api_task_responses(tasks_api, status=status)


@router.get("/{task_name}", response_model=BackupTaskDetailResponse)
async def backup_mongo_api_detail(
    task_name: str,
    tasks_api: TaskAPI,
) -> BackupTaskDetailResponse:
    """Retrieve a single parent backup task with derived sibling status."""
    parent_name = await resolve_backup_parent_task_name(task_name, tasks_api)
    task = await get_backups_task(parent_name, tasks_api)
    return await build_backup_mongo_api_detail_response(task, tasks_api)


@router.post(
    "/",
    response_model=BackupTaskDetailResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def backup_mongo_api_create(
    body: BackupTaskWrite,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> BackupTaskDetailResponse:
    """Create a backup task group from a JSON payload request body.

    POSTs the parent ``pbm_config`` task, then derived ``pbm_logical``,
    ``pbm_physical``, and ``pbm_status`` siblings via
    :func:`~app.sep.plugins.framework.cascade.cascade_create_tasks`.
    """
    logger.debug("Create backup_mongo task group (JSON path): %s", body.task_name)
    create_body = body.model_copy(update={"backup_type": BackupType.PBM_CONFIG})
    form = backup_create_from_write(create_body)
    task_write = await build_backup_task_payload(form, inventory_api)
    parent_payload = task_write.model_dump()
    derived_specs = backup_mongo_schema.derived or []
    await cascade_create_tasks(tasks_api, parent_payload, derived_specs)
    task = await get_backups_task(task_write.name, tasks_api)
    return await build_backup_mongo_api_detail_response(task, tasks_api)


@router.post(
    "/{task_name}/execute",
    response_model=BackupExecutionResponse,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[IsApiAuthenticated, HasNoConflictedRunningTasks],
)
async def backup_mongo_api_execute(
    task_name: str,
    body: BackupExecuteWrite,
    tasks_api: TaskAPI,
) -> BackupExecutionResponse:
    """Execute a backup task."""
    task = await get_backups_task(task_name, tasks_api)
    logger.info("Executing backup_mongo task %r", task.name)
    created = await tasks_api.post(
        f"/execute/{task.name}",
        json=body.model_dump(exclude_none=True),
    )
    task_history = TaskHistoryResponse.model_validate(created)
    return BackupExecutionResponse(
        task_name=task.name,
        task_id=task_history.id,
    )


@router.delete("/{task_name}", status_code=http_status.HTTP_204_NO_CONTENT)
async def backup_mongo_api_delete(
    task_name: str,
    tasks_api: TaskAPI,
) -> None:
    """Delete a backup task group."""
    parent_name = await resolve_backup_parent_task_name(task_name, tasks_api)
    await get_backups_task(parent_name, tasks_api)
    await cascade_delete_tasks(
        tasks_api,
        parent_name,
        backup_derived_task_names(parent_name),
    )
