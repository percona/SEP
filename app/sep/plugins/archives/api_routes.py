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
level; the ``schema_endpoint`` helper also pins ``IsApiAuthenticated`` per
route for safety.
"""

import logging

from fastapi import APIRouter
from fastapi import status as http_status

from app.sep.deps import IsApiAuthenticated, TaskAPI
from app.sep.plugins.archives.deps import (
    ArchivesApiGeneratedTask,
    ArchivesTask,
)
from app.sep.plugins.archives.schema import archives_schema
from app.sep.plugins.framework.api import schema_endpoint
from app.tasks.models import Task

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=archives_schema)


@router.get("/", response_model=list[dict], dependencies=[IsApiAuthenticated])
async def archives_api_list(tasks_api: TaskAPI) -> list[dict]:
    """List archive tasks."""
    result = await tasks_api.get("/", params={"owner": "archiver"})
    return result.get("items", [])


@router.get("/{task_name}", response_model=dict, dependencies=[IsApiAuthenticated])
async def archives_api_detail(task: ArchivesTask) -> dict:
    """Retrieve a single archive task."""
    return task.model_dump(mode="json")


@router.post(
    "/",
    response_model=dict,
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[IsApiAuthenticated],
)
async def archives_api_create(
    task_write: ArchivesApiGeneratedTask,
    tasks_api: TaskAPI,
) -> dict:
    """Create an archive task from a JSON payload request body."""
    logger.debug("Create archives task (JSON path): %s", task_write.name)
    created = await tasks_api.post("/", json=task_write.model_dump())
    task = Task.model_validate(created)
    return task.model_dump(mode="json")


@router.delete(
    "/{task_name}",
    status_code=http_status.HTTP_204_NO_CONTENT,
    dependencies=[IsApiAuthenticated],
)
async def archives_api_delete(task: ArchivesTask, tasks_api: TaskAPI) -> None:
    """Delete an archive task."""
    await tasks_api.delete(f"/{task.name}")
