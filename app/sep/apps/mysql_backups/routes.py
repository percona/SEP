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
from typing import Annotated

import yaml
from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import FutureDatetime

from app.core.alerts.config import alert_settings
from app.core.pagination import fetch_all_dict_items
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.deprecation import DeprecatedJinja2Route
from app.sep.apps.mysql_backups.deps import (
    BackupGeneratedTask,
    BackupsIndexContext,
    BackupsTask,
    parse_backup_task_data,
)
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.config import sep_settings
from app.sep.connectivity import maybe_check_connectivity
from app.sep.deps import (
    CheckConnectivityFlag,
    DefaultContext,
    ExecutorHostsCtx,
    get_chainable_tasks,
    HasNoConflictedRunningTasks,
    InventoryAPI,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
# Jinja2 UI deprecated — React replacement at /apps/mysql_backups.
router = APIRouter(route_class=DeprecatedJinja2Route)
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def mysql_backups_index(
    request: Request,
    context: BackupsIndexContext,
) -> HTMLResponse:
    """Homepage of backups plugin."""
    return templates.TemplateResponse(
        request=request,
        name="mysql_backups/backup/index.html.j2",
        context=context,
    )


@router.get("/docs", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def mysql_backups_docs(request: Request, context: DefaultContext) -> HTMLResponse:
    """Standalone documentation page for backup configuration."""
    return templates.TemplateResponse(
        request=request,
        name="mysql_backups/backup/docs.html.j2",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def mysql_backups_create(
    request: Request,
    task: BackupGeneratedTask,
    task_api: TaskAPI,
    *,
    check_connectivity: CheckConnectivityFlag,
) -> RedirectResponse:
    """Create new backups task."""
    logger.debug("Create backups task: %s", task)
    await task_api.post(
        "/",
        json=task.model_dump(),
    )
    await maybe_check_connectivity(
        request,
        task_api,
        task.data.get("meta", {}),
        check_connectivity=check_connectivity,
    )
    task_path = request.url_for("mysql_backups_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def mysql_backups_detail(
    task: BackupsTask,
    request: Request,
    context: DefaultContext,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    executor_hosts_ctx: ExecutorHostsCtx,
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
        "executor_host_ip": executor_hosts_ctx.hosts.get(meta["target"]),
        "port": server_config.get("PORT") or 3306,
        "backup_type": backup_type,
        "entities": {entity.name: entity.value for entity in decoded_entities},
        "delete_url": request.url_for("mysql_backups_delete", task_name=task.name),
        "config": task_config.get("ALL_SERVERS", {}),
        "is_edit_enabled": not task.protected,
        "alert_on_fail": task.alert_on_fail,
    }

    task_data.update(parsed_task_data)

    context["task"] = task_data
    response = await tasks_api.get(f"/{task.name}/history/")
    context["history"] = response["items"]
    response = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["running_tasks"] = response["items"]
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")

    context["executor_hosts"] = executor_hosts_ctx.with_host(
        task_data["hostname"]
    ).as_template_list()
    context["executor_hosts_dict"] = executor_hosts_ctx.hosts

    try:
        context["services"] = await fetch_all_dict_items(
            lambda pagination: inventory_api.get(
                "/services/",
                params={
                    "service_type": ServiceTypeEnum.MYSQL,
                    **pagination.model_dump(),
                },
            )
        )
    except HTTPException:
        context["services"] = []

    context["alert_on_fail_default"] = task.alert_on_fail
    context["alert_on_fail_available"] = bool(alert_settings.PROVIDERS)
    context["chainable_tasks"] = await get_chainable_tasks(
        tasks_api, task.owner, meta["target"], task.name
    )

    return templates.TemplateResponse(
        request=request,
        name="mysql_backups/backup/details.html.j2",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated, HasNoConflictedRunningTasks],
    response_class=RedirectResponse,
)
async def mysql_backups_execute(
    request: Request,
    task: BackupsTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
    chain_task_names: Annotated[list[str] | None, Form()] = None,
    chain_on_failure: Annotated[bool | None, Form()] = None,
) -> RedirectResponse:
    """Execute backups task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={
            "eta": eta,
            "chain_task_names": chain_task_names,
            "chain_on_failure": chain_on_failure,
        },
    )
    task_path = request.url_for("mysql_backups_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/update",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def mysql_backups_update(
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
        request.url_for("mysql_backups_detail", task_name=updated_task.name),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def mysql_backups_delete(
    task: BackupsTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete backups task."""
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/mysql_backups", status_code=status.HTTP_303_SEE_OTHER)
