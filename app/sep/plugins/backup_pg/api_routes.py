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
``app/sep/api/router.py``. Authentication is enforced at the
``api_router`` level (``IsApiAuthenticated``); the ``plugins_router``
additionally attaches ``RequireBearerForUnsafeMethods`` so POST/PUT/
PATCH/DELETE require an ``Authorization: Bearer`` header (cookie-only
mutations are rejected with 401 before reaching route logic).
"""

import logging
from datetime import datetime, UTC

from fastapi import APIRouter
from fastapi import status as http_status

from app.core.exceptions import HTTPInternalServerErrorException
from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.sep.deps import (
    HasNoConflictedRunningTasks,
    InventoryAPI,
    TaskAPI,
)
from app.sep.plugins.backup_pg.deps import (
    backup_create_from_write,
    build_backup_pg_api_detail_response,
    build_backup_task_payload,
    get_backup_pg_api_task_responses,
    get_backups_task,
    HasNoConflictedRunningTasksOnCreate,
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


@router.get("/", response_model=PaginatedResponse[BackupTaskResponse])
async def backup_pg_api_list(
    tasks_api: TaskAPI,
    pagination: PaginationDep,
    status: TaskHistoryStatusEnum | None = None,
) -> PaginatedResponse[BackupTaskResponse]:
    """List pgBackRest backup tasks.

    ``limit`` is capped because each listed task triggers a follow-up
    history fetch in :func:`get_backup_pg_api_task_responses`; an
    unbounded ``limit`` would amplify fan-out to the Tasks API.
    """
    return await get_backup_pg_api_task_responses(
        tasks_api,
        pagination=pagination,
        status=status,
    )


@router.get("/{task_name}", response_model=BackupTaskDetailResponse)
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
    response_model=BackupTaskDetailResponse,
    dependencies=[HasNoConflictedRunningTasksOnCreate],
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
    response_model=BackupExecutionResponse,
    dependencies=[HasNoConflictedRunningTasks],
)
async def backup_pg_api_execute(
    task_name: str,
    body: BackupExecuteWrite,
    tasks_api: TaskAPI,
) -> BackupExecutionResponse:
    """Execute a pgBackRest backup task.

    If ``body.eta`` is non-null but already in the past (e.g. because of
    client/server clock skew or request latency), it is dropped from the
    upstream payload and the task is dispatched immediately rather than
    rejecting the request with a 422.
    """
    task = await get_backups_task(task_name, tasks_api)
    logger.info("Executing backup_pg task %r", task.name)
    exclude: set[str] = set()
    if body.eta is not None:
        now = (
            datetime.now(tz=body.eta.tzinfo)
            if body.eta.tzinfo
            else datetime.now(tz=UTC).replace(tzinfo=None)
        )
        if body.eta <= now:
            exclude.add("eta")
    created = await tasks_api.post(
        f"/execute/{task.name}",
        json=body.model_dump(mode="json", exclude_none=True, exclude=exclude),
    )
    task_history = TaskHistoryResponse.model_validate(created)
    return BackupExecutionResponse(
        task_name=task.name,
        task_id=task_history.id,
    )


@router.delete(
    "/{task_name}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    dependencies=[HasNoConflictedRunningTasks],
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
        raise HTTPInternalServerErrorException(
            detail=f"Partial delete failure; orphaned tasks: {failed}",
        )
