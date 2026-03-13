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

"""Define routes for the backups plugin."""

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
    HasNoConflictedRunningTasks,
    InventoryAPI,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.plugins.backup.deps import (
    BackupGeneratedTask,
    BackupsTask,
    get_backups_index_context,
    parse_backup_task_data,
)
from app.sep.plugins.backup.models import BackupType
from app.tasks.models import TaskHistoryStatusEnum

from .restore.routes import router as restore_router

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES

router.include_router(restore_router, prefix="/restores", tags=["restores"])


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def backups_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_backups_index_context)],
) -> HTMLResponse:
    """Homepage of backups plugin."""
    return templates.TemplateResponse(
        request=request,
        name="backups/backup/index.html.j2",
        context=context,
    )


@router.get("/docs", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def backups_docs(request: Request, context: DefaultContext) -> HTMLResponse:
    """Standalone documentation page for backup configuration."""
    return templates.TemplateResponse(
        request=request,
        name="backups/backup/docs.html.j2",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def backups_create(
    request: Request,
    task: BackupGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create new backups task."""
    logger.debug("Create backups task: %s", task)
    await task_api.post(
        "/",
        json=task.model_dump(),
    )
    task_path = request.url_for("backups_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def backups_detail(
    task: BackupsTask,
    request: Request,
    context: DefaultContext,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve backups task."""
    data = task.data
    meta = data["meta"]
    decoded_entities = task.anonymized_entities
    task_config = yaml.safe_load(meta["config"])
    server_config = task_config["SERVER_LIST"][0]

    parsed_task_data = parse_backup_task_data(task.model_dump())

    host = server_config["HOST"]
    backup_type = BackupType(server_config["BACKUP_TYPE"]).name
    db_host_for_display = (
        meta["target"]
        if host in ("localhost", "127.0.0.1") and server_config["BACKUP_TYPE"] == "X"
        else host
    )

    try:
        executor_hosts = await tasks_api.get("/hosts/")
        executor_host_ip = (
            executor_hosts.get(meta["target"])
            if isinstance(executor_hosts, dict)
            else None
        )
    except HTTPException:
        executor_hosts = {}
        executor_host_ip = None

    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": task.created_by,
        "last_updated_by": task.last_updated_by,
        "hostname": meta["target"],
        "meta": meta,
        "host": host,
        "db_host_for_display": db_host_for_display,
        "executor_host_ip": executor_host_ip,
        "port": server_config.get("PORT") or 3306,
        "backup_type": backup_type,
        "entities": {entity.name: entity.value for entity in decoded_entities},
        "delete_url": request.url_for("backups_delete", task_name=task.name),
        "config": task_config.get("ALL_SERVERS", {}),
        "is_edit_enabled": not task.protected,
        "alert_on_fail": task.alert_on_fail,
    }

    task_data.update(parsed_task_data)

    context["task"] = task_data
    context["history"] = await tasks_api.get(f"/{task.name}/history/")
    context["running_tasks"] = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")

    context["executor_hosts"] = (
        set(executor_hosts) | {task_data["hostname"]}
        if isinstance(executor_hosts, dict)
        else {task_data["hostname"]}
    )
    context["executor_hosts_dict"] = (
        executor_hosts if isinstance(executor_hosts, dict) else {}
    )

    try:
        services = await inventory_api.get(
            "/services/", params={"service_type": ServiceTypeEnum.MYSQL}
        )
        context["services"] = services
    except HTTPException:
        context["services"] = []

    context["alert_on_fail_default"] = task.alert_on_fail
    context["alert_on_fail_available"] = bool(alert_settings.PROVIDERS)

    return templates.TemplateResponse(
        request=request,
        name="backups/backup/details.html.j2",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated, HasNoConflictedRunningTasks],
    response_class=RedirectResponse,
)
async def backups_execute(
    request: Request,
    task: BackupsTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
) -> RedirectResponse:
    """Execute backups task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={"eta": eta},
    )  # TODO: send meta form fields  # noqa: TD002, TD003
    task_path = request.url_for("backups_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/update",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def backups_update(
    request: Request,
    task_name: str,
    updated_task: BackupGeneratedTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Update backups task."""
    logger.debug("Updating backups task: %s", updated_task)
    await tasks_api.put(
        f"/{task_name}",
        json=updated_task.model_dump(),
    )
    return RedirectResponse(
        request.url_for("backups_detail", task_name=updated_task.name),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def backups_delete(
    task: BackupsTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete backups task."""
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/backups", status_code=status.HTTP_303_SEE_OTHER)
