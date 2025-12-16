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


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def restores_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_restores_index_context)],
) -> HTMLResponse:
    """Homepage of restores plugin."""
    return templates.TemplateResponse(
        request=request,
        name="backup_mongo/restore/index.html",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def restores_create(
    request: Request,
    tasks: RestoreTasks,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create new restores task."""
    config_task, restore_task = tasks
    logger.debug("Create restores config task: %s", config_task)
    logger.debug("Create restores task: %s", restore_task)

    # Create the config task first
    await task_api.post(
        "/",
        json=config_task.model_dump(),
    )

    # Create the restore task
    await task_api.post(
        "/",
        json=restore_task.model_dump(),
    )

    task_path = request.url_for("restores_detail", task_name=config_task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
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
        task_path = request.url_for("restores_detail", task_name=data.get("parent"))
        return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)

    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    server_config = task_config["SERVER_LIST"][0]

    parsed_task_data = parse_restore_task_data(task.model_dump())

    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": task.created_by,
        "last_updated_by": task.last_updated_by,
        "hostname": meta["target"],
        "meta": meta,
        "host": server_config.get("DEST_HOST"),
        "port": server_config.get("DEST_PORT") or 27017,
        "restore_type": BackupType(server_config["BACKUP_TYPE"]).name,
        "backup_source": server_config.get("BACKUP_SOURCE"),
        "delete_url": request.url_for("restores_delete", task_name=task.name),
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

    return templates.TemplateResponse(
        request=request,
        name="backup_mongo/restore/details.html",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def restores_execute(
    request: Request,
    task: RestoresTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
) -> RedirectResponse:
    """Execute restores task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={"eta": eta},
    )  # TODO: send meta form fields  # noqa: TD002, TD003
    task_path = request.url_for("restores_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/update",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
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
        request.url_for("restores_detail", task_name=updated_task.name),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def restores_delete(
    request: Request,
    task: RestoresTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete restores task."""
    await tasks_api.delete(f"/{task.name}")
    task_path = request.url_for("restores_index")
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)
