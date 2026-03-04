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

"""Define routes for the restores plugin."""

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
    InventoryAPI,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.plugins.backup_mongo.models import BackupType
from app.sep.plugins.backup_mongo.restore.deps import (
    get_restores_index_context,
    parse_restore_task_data,
    RestoreGeneratedTask,
    RestoresTask,
    RestoreTasks,
)
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


def _build_task_urls(
    task_name: str, task_config: dict[str, Any], request: Request
) -> dict[str, str | None]:
    """Build URLs for task action buttons."""
    sync_config_url = request.url_for("pbm_restores_execute", task_name=task_name)
    restore_task_name = f"{task_name}-{task_config.get('backupType')}"
    restore_url = request.url_for("pbm_restores_execute", task_name=restore_task_name)
    pbm_list_task_name = f"{task_name}-pbm-list"
    pbm_list_url = request.url_for("pbm_restores_execute", task_name=pbm_list_task_name)

    force_resync_url = None
    if BackupType(task_config.get("backupType")) == BackupType.PBM_PHYSICAL:
        force_resync_task_name = f"{task_name}-pbm-force-resync"
        force_resync_url = request.url_for(
            "pbm_restores_execute", task_name=force_resync_task_name
        )

    return {
        "sync_config_url": sync_config_url,
        "restore_url": restore_url,
        "pbm_list_url": pbm_list_url,
        "force_resync_url": force_resync_url,
    }


async def _fetch_running_tasks(
    task_name: str,
    task_config: dict[str, Any],
    tasks_api: TaskAPI,
) -> list[dict[str, Any]]:
    """Fetch running tasks for parent and child tasks."""
    running_tasks = await tasks_api.get(
        f"/{task_name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )

    restore_task_name = f"{task_name}-{task_config.get('backupType')}"
    running_tasks += await tasks_api.get(
        f"/{restore_task_name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )

    pbm_list_task_name = f"{task_name}-pbm-list"
    running_tasks += await tasks_api.get(
        f"/{pbm_list_task_name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )

    if BackupType(task_config.get("backupType")) == BackupType.PBM_PHYSICAL:
        force_resync_task_name = f"{task_name}-pbm-force-resync"
        running_tasks += await tasks_api.get(
            f"/{force_resync_task_name}/history/",
            params={"status": TaskHistoryStatusEnum.RUNNING},
        )

    return running_tasks


async def _fetch_task_history(
    task_name: str,
    task_config: dict[str, Any],
    tasks_api: TaskAPI,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch history for child tasks."""
    pbm_list_task_name = f"{task_name}-pbm-list"

    try:
        history_pbm_list = await tasks_api.get(f"/{pbm_list_task_name}/history/")
    except HTTPException:
        history_pbm_list = []

    if BackupType(task_config.get("backupType")) == BackupType.PBM_PHYSICAL:
        force_resync_task_name = f"{task_name}-pbm-force-resync"
        try:
            history_force_resync = await tasks_api.get(
                f"/{force_resync_task_name}/history/"
            )
        except HTTPException:
            history_force_resync = []
    else:
        history_force_resync = []

    return {
        "history_pbm_list": history_pbm_list,
        "history_force_resync": history_force_resync,
    }


@router.get(
    "/",
    dependencies=[IsAuthenticated],
    response_class=HTMLResponse,
    name="pbm_restores_index",
)
async def restores_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_restores_index_context)],
) -> HTMLResponse:
    """Homepage of restores plugin."""
    return templates.TemplateResponse(
        request=request,
        name="backup_mongo/restore/index.html.j2",
        context=context,
    )


@router.post(
    "/",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=HTMLResponse,
    name="pbm_restores_create",
)
async def restores_create(
    request: Request,
    tasks: RestoreTasks,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create new restores task."""
    config_task, restore_task, pbm_list_task, force_resync_task = tasks
    logger.debug("Create restores config task: %s", config_task)
    logger.debug("Create restores task: %s", restore_task)
    logger.debug("Create pbm list task: %s", pbm_list_task)
    if force_resync_task:
        logger.debug("Create pbm force-resync task: %s", force_resync_task)

    await task_api.post(
        "/",
        json=config_task.model_dump(),
    )

    await task_api.post(
        "/",
        json=restore_task.model_dump(),
    )

    await task_api.post(
        "/",
        json=pbm_list_task.model_dump(),
    )

    if force_resync_task:
        await task_api.post(
            "/",
            json=force_resync_task.model_dump(),
        )

    task_path = request.url_for("pbm_restores_detail", task_name=config_task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get(
    "/{task_name}",
    dependencies=[IsAuthenticated],
    response_class=HTMLResponse,
    name="pbm_restores_detail",
)
async def restores_detail(
    task: RestoresTask,
    request: Request,
    context: DefaultContext,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve restores task."""
    data = task.data

    # If the task has a parent, redirect to the parent task detail page
    if data.get("parent"):
        task_path = request.url_for("pbm_restores_detail", task_name=data.get("parent"))
        return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)

    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])

    if "restore" not in task_config:
        task_config["restore"] = {}

    meta["config"] = yaml.dump(
        task_config, default_flow_style=False, allow_unicode=True
    )

    parsed_task_data = parse_restore_task_data(task.model_dump())

    urls = _build_task_urls(task.name, task_config, request)

    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": task.created_by,
        "last_updated_by": task.last_updated_by,
        "hostname": meta["target"],
        "meta": meta,
        "restore_type": BackupType(task_config.get("backupType")).name,
        "backup_source": task_config.get("backupSource"),
        "delete_url": request.url_for("pbm_restores_delete", task_name=task.name),
        "is_edit_enabled": not task.protected,
        "alert_on_fail": task.alert_on_fail,
        **urls,
    }

    task_data.update(parsed_task_data)

    context["task"] = task_data
    all_history = await tasks_api.get(f"/{task.name}/history/")
    context["history"] = all_history

    try:
        context["history_logical"] = await tasks_api.get(
            f"/{task.name}-pbm_logical/history/"
        )
    except HTTPException:
        context["history_logical"] = []

    try:
        context["history_physical"] = await tasks_api.get(
            f"/{task.name}-pbm_physical/history/"
        )
    except HTTPException:
        context["history_physical"] = []

    context["running_tasks"] = await _fetch_running_tasks(
        task.name, task_config, tasks_api
    )

    child_history = await _fetch_task_history(task.name, task_config, tasks_api)
    context.update(child_history)

    context["stats"] = await tasks_api.get(f"/stats/{task.name}")

    try:
        executor_hosts = await tasks_api.get("/hosts/")
        context["executor_hosts"] = set(executor_hosts) | {task_data["hostname"]}
    except HTTPException:
        context["executor_hosts"] = {task_data["hostname"]}

    try:
        services = await inventory_api.get(
            "/services/", params={"service_type": ServiceTypeEnum.MONGODB}
        )
        for service in services:
            service["schemas"] = await inventory_api.get(
                f"/services/{service['id']}/schemas/",
            )
        context["services"] = services
    except HTTPException:
        context["services"] = []

    context["alert_on_fail_default"] = task.alert_on_fail
    context["alert_on_fail_available"] = bool(alert_settings.PROVIDERS)
    context["chainable_tasks"] = await get_chainable_tasks(
        tasks_api, task.owner, meta["target"], task.name
    )

    return templates.TemplateResponse(
        request=request,
        name="backup_mongo/restore/details.html.j2",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
    name="pbm_restores_execute",
)
async def restores_execute(
    request: Request,
    task: RestoresTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
    chain_task_names: Annotated[list[str] | None, Form()] = None,
) -> RedirectResponse:
    """Execute restores task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={"eta": eta, "chain_task_names": chain_task_names},
    )
    task_path = request.url_for("pbm_restores_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/update",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
    name="pbm_restores_update",
)
async def restores_update(
    request: Request,
    task_name: str,
    updated_task: RestoreGeneratedTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Update restores task."""
    logger.debug("Updating restores task: %s", updated_task)
    await tasks_api.put(
        f"/{task_name}",
        json=updated_task.model_dump(),
    )
    return RedirectResponse(
        request.url_for("pbm_restores_detail", task_name=updated_task.name),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
    name="pbm_restores_delete",
)
async def restores_delete(
    request: Request,
    task: RestoresTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete restores task."""
    await tasks_api.delete(f"/{task.name}")
    task_path = request.url_for("pbm_restores_index")
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)
