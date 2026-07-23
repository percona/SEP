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

"""Define the custom JSON API routes for the backup_mongo plugin.

The declarative :class:`~app.sep.apps.framework.apps.TaskExecutionApp` in
``app.py`` derives the ``GET /schema`` and paginated ``roots_only`` +
``backup_type`` list routes; this router carries the per-app routes it keeps
custom — the sibling-aggregating detail, the cascade create/update/delete, and
the execute route — served as its ``extra_routes``. The framework's derived detail
route is suppressed (``capabilities.detail=False``) so the custom ``GET
/{task_name}`` here wins. The restore subpackage is now a structurally-bound
child app (declared via ``child_apps`` on the parent), not a ``/restores``
sub-router mounted here.
"""

from fastapi import APIRouter
from fastapi import status as http_status

from app.core.exceptions import HTTPInternalServerErrorException
from app.sep.apps.backup_mongo.deps import (
    backup_create_from_write,
    backup_derived_task_names,
    BackupCascadePlan,
    BackupsTask,
    build_backup_mongo_api_detail_response,
    EditableBackupParent,
    ensure_backup_group_update_preserves_names,
    get_backups_task,
    resolve_backup_parent_task,
    update_backup_task_group,
)
from app.sep.apps.backup_mongo.models import (
    BackupTaskDetailResponse,
    BackupTaskWrite,
)
from app.sep.apps.framework.api import derive_cascade_create_route, derive_execute_route
from app.sep.apps.framework.cascade import cascade_delete_tasks
from app.sep.deps import (
    InventoryAPI,
    TaskAPI,
)

router = APIRouter()


@router.get("/{task_name}")
async def backup_mongo_api_detail(
    task_name: str,
    tasks_api: TaskAPI,
) -> BackupTaskDetailResponse:
    """Retrieve a single parent backup task with derived sibling status."""
    parent_task = await resolve_backup_parent_task(task_name, tasks_api)
    return await build_backup_mongo_api_detail_response(parent_task, tasks_api)


derive_cascade_create_route(
    router,
    name="backup_mongo_api_create",
    description="Create a backup task group from a JSON payload request body.",
    create_plan=BackupCascadePlan,
    get_task=get_backups_task,
    response_builder=build_backup_mongo_api_detail_response,
    response_model=BackupTaskDetailResponse,
    connectivity_check=False,
)


derive_execute_route(
    router,
    name="backup_mongo_api_execute",
    description="Execute a backup task.",
    task_dep=BackupsTask,
)


@router.put("/{task_name}")
async def backup_mongo_api_update(
    parent_task: EditableBackupParent,
    body: BackupTaskWrite,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> BackupTaskDetailResponse:
    """Update a backup task group from a JSON payload request body.

    Cascade-updates the parent ``pbm_config`` task and its derived logical,
    physical, status, and incremental siblings, re-stamping ``_form`` so the edit page keeps
    prefilling. The ``EditableBackupParent`` dependency resolves a satellite URL
    to the parent and blocks protected or in-flight groups before any write.
    Rejects a parent rename with a conflict and surfaces a partial cascade
    failure as an HTTP 500 naming the failed legs.
    """
    ensure_backup_group_update_preserves_names(parent_task.name, body.task_name)
    form = backup_create_from_write(body)
    result = await update_backup_task_group(tasks_api, parent_task, form, inventory_api)
    if not result.success:
        failed = [
            (failure.task_name, str(failure.exception)) for failure in result.failures
        ]
        raise HTTPInternalServerErrorException(
            detail=f"Partial update failure; inconsistent task group: {failed}"
        )
    updated_task = await get_backups_task(parent_task.name, tasks_api)
    return await build_backup_mongo_api_detail_response(updated_task, tasks_api)


@router.delete("/{task_name}", status_code=http_status.HTTP_204_NO_CONTENT)
async def backup_mongo_api_delete(
    task_name: str,
    tasks_api: TaskAPI,
) -> None:
    """Delete a backup task group."""
    parent_task = await resolve_backup_parent_task(task_name, tasks_api)
    result = await cascade_delete_tasks(
        tasks_api,
        parent_task.name,
        backup_derived_task_names(parent_task.name),
    )
    if not result.success:
        failed = [
            (failure.task_name, str(failure.exception)) for failure in result.failures
        ]
        raise HTTPInternalServerErrorException(
            detail=f"Partial delete failure; orphaned tasks: {failed}"
        )
