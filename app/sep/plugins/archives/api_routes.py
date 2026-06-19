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

"""Define the JSON API router for the Archives plugin.

Mounted at ``/api/plugins/archives/`` via ``plugins_router`` in
``app/sep/api/router.py``. Authentication is enforced at the ``api_router``
level; per-route ``IsApiAuthenticated`` declarations are not repeated here.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.sep.deps import TaskAPI
from app.sep.plugins.archives.deps import (
    ArchivesApiGeneratedTask,
    ArchivesTask,
    build_archives_api_task_response,
    get_archives_api_task_responses,
)
from app.sep.plugins.archives.models import (
    ArchivesCreateResponse,
    ArchivesTaskResponse,
)
from app.sep.plugins.archives.schema import archives_schema
from app.sep.plugins.framework import (
    get_task_latest_status,
    maybe_record_connectivity_warning,
)
from app.sep.plugins.framework.api import schema_endpoint
from app.tasks.models import Task

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=archives_schema)


@router.get("/")
async def archives_api_list(tasks_api: TaskAPI) -> list[ArchivesTaskResponse]:
    """List archive tasks."""
    return await get_archives_api_task_responses(tasks_api)


@router.get("/{task_name}")
async def archives_api_detail(
    task: ArchivesTask,
    tasks_api: TaskAPI,
) -> ArchivesTaskResponse:
    """Retrieve a single archive task."""
    task_status = await get_task_latest_status(tasks_api, task.name)
    return build_archives_api_task_response(task, status=task_status)


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
)
async def archives_api_create(
    task_write: ArchivesApiGeneratedTask,
    tasks_api: TaskAPI,
    *,
    check_connectivity: Annotated[bool, Query()] = True,
) -> ArchivesCreateResponse:
    """Create an archive task from a JSON payload request body.

    :param check_connectivity: Whether to verify the target database is
        reachable after task creation. Defaults to ``True`` so callers that
        omit the parameter still get a connectivity round-trip; pass
        ``check_connectivity=false`` to opt out. Mirrors the asymmetric
        default used by the checksums create flow (the Form path defaults
        to ``False`` because HTML checkboxes omit the field when unchecked).
    :type check_connectivity: bool
    """
    logger.debug("Create archives task (JSON path): %s", task_write.name)
    created = await tasks_api.post("/", json=task_write.model_dump())
    task = Task.model_validate(created)
    connectivity_warning = await maybe_record_connectivity_warning(
        tasks_api,
        task.data.get("meta", {}),
        check_connectivity=check_connectivity,
    )
    base = build_archives_api_task_response(task, status=None)
    return ArchivesCreateResponse(
        **base.model_dump(),
        connectivity_warning=connectivity_warning,
    )


@router.delete("/{task_name}", status_code=status.HTTP_204_NO_CONTENT)
async def archives_api_delete(task: ArchivesTask, tasks_api: TaskAPI) -> None:
    """Delete an archive task."""
    await tasks_api.delete(f"/{task.name}")
