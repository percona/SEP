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

"""Define the custom JSON API routes for the backup_mongo restore app.

The declarative :class:`~app.sep.apps.framework.apps.TaskExecutionApp` in
``app.py`` derives the ``GET /schema`` and ``POST /{task_name}/execute`` routes;
this router carries the routes the restore task group keeps custom — the union
list, the sibling-aggregating detail, and the cascade create / update / delete —
served as the app's ``extra_routes``. The derived list and detail are suppressed
(``capabilities.list=False`` / ``capabilities.detail=False``) so these custom
routes win their paths. Authentication is inherited from the ``/api`` router.
"""

import logging

from fastapi import APIRouter
from fastapi import status as http_status

from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.sep.apps.backup_mongo.restore.deps import (
    build_restore_mongo_api_detail_response,
    build_restore_mongo_api_task_response,
    delete_restore_task_group,
    EditableRestoreParent,
    get_restore_mongo_api_task_responses,
    get_restores_task,
    RestoreCascadePlan,
    RestoreParentTask,
    RestoreUpdateFormFromBody,
    update_restore_task_group,
)
from app.sep.apps.backup_mongo.restore.models import (
    RestoreTaskDetailResponse,
    RestoreTaskResponse,
)
from app.sep.apps.framework import get_task_latest_history
from app.sep.apps.framework.api import derive_cascade_create_route
from app.sep.deps import (
    InventoryAPI,
    TaskAPI,
)
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)

router = APIRouter()


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


derive_cascade_create_route(
    router,
    name="restore_mongo_api_create",
    description="Create a restore task group from a JSON payload request body.",
    create_plan=RestoreCascadePlan,
    get_task=get_restores_task,
    response_builder=build_restore_mongo_api_detail_response,
    response_model=RestoreTaskDetailResponse,
    connectivity_check=False,
)


@router.put("/{task_name}")
async def restore_mongo_api_update(
    parent_task: EditableRestoreParent,
    form: RestoreUpdateFormFromBody,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> RestoreTaskResponse:
    """Update a restore task from a JSON payload request body.

    PUTs the parent config payload to the config task name and refreshes each
    child leg (restore, pbm-list, optional force-resync) in place. The
    ``EditableRestoreParent`` dependency resolves a satellite URL to the parent
    and blocks protected or in-flight groups before any write.
    """
    logger.debug("Update backup_mongo restore task (JSON path): %s", parent_task.name)
    updated_task = await update_restore_task_group(
        tasks_api,
        parent_task,
        form,
        inventory_api,
    )
    latest = await get_task_latest_history(tasks_api, updated_task.name)
    return build_restore_mongo_api_task_response(
        updated_task, status=latest.status, last_executed_at=latest.finished_at
    )


@router.delete("/{task_name}", status_code=http_status.HTTP_204_NO_CONTENT)
async def restore_mongo_api_delete(
    parent_task: RestoreParentTask,
    tasks_api: TaskAPI,
) -> None:
    """Delete a restore task group."""
    await delete_restore_task_group(tasks_api, parent_task)
