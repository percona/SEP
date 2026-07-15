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
custom — the sibling-aggregating detail, the cascade create/delete, and the
execute route — served as its ``extra_routes``. The framework's derived detail
route is suppressed (``capabilities.detail=False``) so the custom ``GET
/{task_name}`` here wins. The restore subpackage is now a structurally-bound
child app (declared via ``child_apps`` on the parent), not a ``/restores``
sub-router mounted here.
"""

from fastapi import APIRouter
from fastapi import status as http_status

from app.core.exceptions import HTTPInternalServerErrorException
from app.sep.apps.backup_mongo.deps import (
    backup_derived_task_names,
    BackupCascadePlan,
    BackupsTask,
    build_backup_mongo_api_detail_response,
    get_backups_task,
    resolve_backup_parent_task,
)
from app.sep.apps.backup_mongo.models import (
    BackupTaskDetailResponse,
)
from app.sep.apps.framework.api import derive_cascade_create_route, derive_execute_route
from app.sep.apps.framework.cascade import cascade_delete_tasks
from app.sep.deps import (
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
