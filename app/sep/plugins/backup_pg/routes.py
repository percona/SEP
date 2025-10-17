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
from app.sep.plugins.backup_pg.deps import (
    BackupGeneratedTask,
    BackupsTask,
    get_backups_index_context,
    parse_backup_task_data,
)
from app.sep.plugins.backup_pg.models import BackupType
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def pg_backups_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_backups_index_context)],
) -> HTMLResponse:
    """Homepage of PG backups plugin."""
    return templates.TemplateResponse(
        request=request,
        name="backup_pg/index.html",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def pg_backups_create(
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
    task_path = request.url_for("pg_backups_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def pg_backups_detail(
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

    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "hostname": meta["target"],
        "meta": meta,
        "host": server_config["HOST"],
        "port": server_config.get("PORT") or 3306,
        "backup_type": BackupType(server_config["BACKUP_TYPE"]).name,
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

    try:
        executor_hosts = await tasks_api.get("/hosts/")
        context["executor_hosts"] = set(executor_hosts) | {task_data["hostname"]}
    except HTTPException:
        executor_hosts = {}
        context["executor_hosts"] = {task_data["hostname"]}

    try:
        services = await inventory_api.get(
            "/services/", params={"service_type": ServiceTypeEnum.POSTGRESQL}
        )
        context["services"] = services
    except HTTPException:
        context["services"] = []

    context["alert_on_fail_default"] = task.alert_on_fail
    context["alert_on_fail_available"] = bool(alert_settings.PROVIDERS)

    return templates.TemplateResponse(
        request=request,
        name="backup_pg/details.html",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated, HasNoConflictedRunningTasks],
    response_class=RedirectResponse,
)
async def pg_backups_execute(
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
    task_path = request.url_for("pg_backups_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)
