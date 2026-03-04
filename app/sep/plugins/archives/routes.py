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

"""Define routes for the archivers plugin."""

import logging
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import FutureDatetime

from app.core.alerts.config import alert_settings
from app.inventory.models import ServiceTypeEnum
from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    get_chainable_tasks,
    HasNoConflictedRunningTasks,
    InventoryAPI,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.middleware import messages
from app.sep.plugins.archives.deps import (
    ArchivesGeneratedTask,
    ArchivesTask,
    get_archives_index_context,
)
from app.sep.plugins.archives.models import PurgeConfigItem
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def archives_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_archives_index_context)],
) -> HTMLResponse:
    """Homepage of archives plugin."""
    return templates.TemplateResponse(
        request=request,
        name="archiver/index.html.j2",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def archives_create(
    request: Request,
    task: ArchivesGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create new archives task."""
    logger.debug("Create archives task: %s", task)
    await task_api.post(
        "/",
        json=task.model_dump(),
    )
    task_path = request.url_for("archives_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def archives_detail(
    task: ArchivesTask,
    request: Request,
    context: DefaultContext,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve archives task."""
    data = task.data
    meta = data["meta"]
    decoded_entities = task.anonymized_entities
    task_config = yaml.safe_load(meta["config"])
    all_server = task_config["ALL"]
    purge_item = task_config["PURGE_LIST"][0]
    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": task.created_by,
        "last_updated_by": task.last_updated_by,
        "hostname": meta["target"],
        "meta": meta,
        "entities": {entity.name: entity.value for entity in decoded_entities},
        "delete_url": request.url_for("archives_delete", task_name=task.name),
        "is_edit_enabled": not task.protected,
        "alert_on_fail": task.alert_on_fail,
    }

    source_db = purge_item.get("SOURCE_DB")
    source_table = purge_item.get("SOURCE_TABLE")
    dest_table = purge_item.get("DEST_TABLE")
    source_query = purge_item.get("SOURCE_QUERY")
    dest_file = purge_item.get("DEST_FILE")

    if source_db and source_table:
        task_data["source_table"] = f"{source_db}.{source_table}"
    if source_db and dest_table:
        task_data["dest_table"] = f"{source_db}.{dest_table}"
    if source_query:
        task_data["source_query"] = source_query
    if dest_file:
        task_data["dest_file"] = dest_file
    task_data["source_host"] = all_server.get("SOURCE_HOST")
    task_data["source_port"] = all_server.get("SOURCE_PORT")
    context["task"] = {
        **task_data,
        **PurgeConfigItem.model_validate(purge_item).model_dump(),
    }
    context["history"] = await tasks_api.get(f"/{task.name}/history/")
    context["running_tasks"] = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")

    try:
        executor_hosts = await tasks_api.get("/hosts/")
    except HTTPException as exc:
        executor_hosts = {}
        messages.error(request, exc.detail)

    services = await inventory_api.get(
        "/services/", params={"service_type": ServiceTypeEnum.MYSQL}
    )
    for service in services:
        service["schemas"] = await inventory_api.get(
            f"/services/{service['id']}/schemas/",
        )
    context["services"] = services

    context["executor_hosts"] = set(executor_hosts) | {task_data["hostname"]}
    context["alert_on_fail_default"] = task.alert_on_fail
    context["alert_on_fail_available"] = bool(alert_settings.PROVIDERS)
    context["chainable_tasks"] = await get_chainable_tasks(
        tasks_api, task.owner, meta["target"], task.name
    )

    return templates.TemplateResponse(
        request=request,
        name="archiver/details.html.j2",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated, HasNoConflictedRunningTasks],
    response_class=RedirectResponse,
)
async def archives_execute(
    request: Request,
    task: ArchivesTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
    chain_task_names: Annotated[list[str] | None, Form()] = None,
) -> RedirectResponse:
    """Execute archives task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={"eta": eta, "chain_task_names": chain_task_names},
    )
    task_path = request.url_for("archives_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/update",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def archives_update(
    request: Request,
    task_name: str,
    updated_task: ArchivesGeneratedTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Update archives task."""
    logger.debug("Updating archives task: %s", updated_task)
    await tasks_api.put(
        f"/{task_name}",
        json=updated_task.model_dump(),
    )
    return RedirectResponse(
        request.url_for("archives_detail", task_name=updated_task.name),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def archives_delete(
    task: ArchivesTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete archives task."""
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/archives", status_code=status.HTTP_303_SEE_OTHER)
