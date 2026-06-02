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

"""Define the JSON API router for the MySQL Backups plugin.

Mounted at ``/api/plugins/mysql_backups/`` via ``plugins_router`` in
``app/sep/api/router.py``.
"""

import logging

from fastapi import APIRouter
from fastapi import status as http_status

from app.core.pagination import (
    make_pagination_dep,
    PaginatedResponse,
)
from app.sep.deps import (
    HasNoConflictedRunningTasks,
    InventoryAPI,
    IsApiAuthenticated,
    TaskAPI,
)
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.mysql_backups.deps import (
    BackupsTask,
    build_backup_task_payload_from_model,
    build_mysql_backups_api_task_response,
    get_backups_task_status,
    get_mysql_backups_api_task_responses,
)
from app.sep.plugins.mysql_backups.models import (
    BackupCreate,
    BackupExecuteWrite,
    BackupExecutionResponse,
    BackupResponse,
)
from app.sep.plugins.mysql_backups.schema import mysql_backups_schema
from app.tasks.models import Task, TaskHistoryResponse, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=mysql_backups_schema)

MYSQL_BACKUPS_MAX_PAGINATION_LIMIT = 50
MySQLBackupsPaginationDep = make_pagination_dep(
    max_limit=MYSQL_BACKUPS_MAX_PAGINATION_LIMIT
)


@router.get("/", response_model=PaginatedResponse[BackupResponse])
async def mysql_backups_api_list(
    tasks_api: TaskAPI,
    pagination: MySQLBackupsPaginationDep,
    status: TaskHistoryStatusEnum | None = None,
) -> PaginatedResponse[BackupResponse]:
    """List MySQL backup tasks.

    ``limit`` is capped because each listed task triggers a follow-up history
    fetch in ``get_mysql_backups_api_task_responses``; an unbounded ``limit``
    would amplify fan-out to the Tasks API.
    """
    return await get_mysql_backups_api_task_responses(
        tasks_api,
        status=status,
        offset=pagination.offset,
        limit=pagination.limit,
    )


@router.get("/{task_name}", response_model=BackupResponse)
async def mysql_backups_api_detail(
    task: BackupsTask,
    tasks_api: TaskAPI,
) -> BackupResponse:
    """Retrieve a single MySQL backup task."""
    task_status = await get_backups_task_status(task.name, tasks_api)
    return build_mysql_backups_api_task_response(task, status=task_status)


@router.post(
    "/",
    response_model=BackupResponse,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[IsApiAuthenticated],
)
async def mysql_backups_api_create(
    body: BackupCreate,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> BackupResponse:
    """Create a MySQL backup task from a JSON request body."""
    logger.debug("Create mysql_backups task (JSON path): %s", body.task_name)
    task_write = await build_backup_task_payload_from_model(body, inventory_api)
    created = await tasks_api.post("/", json=task_write.model_dump())
    task = Task.model_validate(created)
    return build_mysql_backups_api_task_response(task, status=None)


@router.post(
    "/{task_name}/execute",
    response_model=BackupExecutionResponse,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[IsApiAuthenticated, HasNoConflictedRunningTasks],
)
async def mysql_backups_api_execute(
    task: BackupsTask,
    body: BackupExecuteWrite,
    tasks_api: TaskAPI,
) -> BackupExecutionResponse:
    """Execute a MySQL backup task."""
    logger.info("Executing mysql_backups task %r", task.name)
    created = await tasks_api.post(
        f"/execute/{task.name}",
        json=body.model_dump(exclude_none=True),
    )
    task_history = TaskHistoryResponse.model_validate(created)
    return BackupExecutionResponse(task_name=task.name, task_id=task_history.id)


@router.delete(
    "/{task_name}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    dependencies=[IsApiAuthenticated],
)
async def mysql_backups_api_delete(
    task: BackupsTask,
    tasks_api: TaskAPI,
) -> None:
    """Delete a MySQL backup task."""
    await tasks_api.delete(f"/{task.name}")
