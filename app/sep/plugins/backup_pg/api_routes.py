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

"""Define the JSON API router for the backup_pg plugin.

Mounted at ``/api/plugins/backup_pg/`` via ``plugins_router`` in
``app/sep/api/router.py``. Authentication is enforced at the ``api_router``
level; the ``schema_endpoint`` helper also pins ``IsApiAuthenticated`` per
route for safety.
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from app.core.models import PaginatedResponse
from app.sep.deps import (
    HasNoConflictedRunningTasks,
    InventoryAPI,
    IsApiAuthenticated,
    RequireBearerAuth,
    TaskAPI,
)
from app.sep.plugins.backup_pg.deps import (
    backup_create_from_write,
    build_backup_pg_api_detail_response,
    build_backup_task_payload,
    get_backup_pg_api_task_responses,
    get_backups_task,
)
from app.sep.plugins.backup_pg.models import (
    BackupExecuteWrite,
    BackupExecutionResponse,
    BackupTaskDetailResponse,
    BackupTaskResponse,
    BackupTaskWrite,
)
from app.sep.plugins.backup_pg.schema import backup_pg_schema
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.framework.cascade import cascade_create_tasks, cascade_delete_tasks
from app.tasks.models import TaskHistoryResponse, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=backup_pg_schema)


@router.get("/")
async def backup_pg_api_list(
    tasks_api: TaskAPI,
    status: TaskHistoryStatusEnum | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=0, le=200),
) -> PaginatedResponse[BackupTaskResponse]:
    """List pgBackRest backup tasks."""
    return await get_backup_pg_api_task_responses(
        tasks_api, status=status, offset=offset, limit=limit
    )


@router.get("/{task_name}")
async def backup_pg_api_detail(
    task_name: str,
    tasks_api: TaskAPI,
) -> BackupTaskDetailResponse:
    """Retrieve a single pgBackRest backup task by name."""
    task = await get_backups_task(task_name, tasks_api)
    return await build_backup_pg_api_detail_response(task, tasks_api)


@router.post(
    "/",
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[RequireBearerAuth, IsApiAuthenticated],
)
async def backup_pg_api_create(
    body: BackupTaskWrite,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> BackupTaskDetailResponse:
    """Create a pgBackRest backup task from a JSON payload request body.

    POSTs the task via :func:`~app.sep.plugins.framework.cascade.cascade_create_tasks`
    with an empty derived list so any future derived-task wiring lands without
    a route signature change.
    """
    logger.debug("Create backup_pg task (JSON path): %s", body.task_name)
    form = backup_create_from_write(body)
    task_write = await build_backup_task_payload(form, inventory_api)
    parent_payload = task_write.model_dump()
    await cascade_create_tasks(tasks_api, parent_payload, derived_specs=[])
    task = await get_backups_task(task_write.name, tasks_api)
    return await build_backup_pg_api_detail_response(task, tasks_api)


@router.post(
    "/{task_name}/execute",
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[RequireBearerAuth, IsApiAuthenticated, HasNoConflictedRunningTasks],
)
async def backup_pg_api_execute(
    task_name: str,
    body: BackupExecuteWrite,
    tasks_api: TaskAPI,
) -> BackupExecutionResponse:
    """Execute a pgBackRest backup task."""
    task = await get_backups_task(task_name, tasks_api)
    logger.info("Executing backup_pg task %r", task.name)
    created = await tasks_api.post(
        f"/execute/{task.name}",
        json=body.model_dump(mode="json", exclude_none=True),
    )
    task_history = TaskHistoryResponse.model_validate(created)
    return BackupExecutionResponse(
        task_name=task.name,
        task_id=task_history.id,
    )


@router.delete(
    "/{task_name}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    dependencies=[RequireBearerAuth, IsApiAuthenticated, HasNoConflictedRunningTasks],
)
async def backup_pg_api_delete(
    task_name: str,
    tasks_api: TaskAPI,
) -> None:
    """Delete a pgBackRest backup task."""
    task = await get_backups_task(task_name, tasks_api)
    result = await cascade_delete_tasks(tasks_api, task.name, derived_names=[])
    if not result.success:
        failed = [
            (failure.task_name, str(failure.exception)) for failure in result.failures
        ]
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Partial delete failure; orphaned tasks: {failed}",
        )
