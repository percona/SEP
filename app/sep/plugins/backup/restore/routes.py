"""Define routes for the restores plugin."""

import logging
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.sep.config import sep_settings
from app.sep.deps import DefaultContext, IsAuthenticated, IsCsrfValidated, TaskAPI
from app.sep.plugins.backup.models import BackupType
from app.sep.plugins.backup.restore.deps import (
    get_restores_index_context,
    RestoreGeneratedTask,
    RestoresTask,
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
        name="backups/restore/index.html",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def restores_create(
    request: Request,
    task: RestoreGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create new restores task."""
    logger.debug("Create restores task: %s", task)
    await task_api.post(
        "/",
        json=task.model_dump(),
    )
    task_path = request.url_for("restores_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def restores_detail(
    task: RestoresTask,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve restores task."""
    data = task.data
    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    server_config = task_config["SERVER_LIST"][0]
    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "hostname": meta["target"],
        "meta": meta,
        "host": server_config["DEST_HOST"],
        "port": server_config["DEST_PORT"],
        "database": server_config.get("DATABASER"),
        "restore_type": BackupType(server_config["BACKUP_TYPE"]).name,
        "delete_url": request.url_for("restores_detail", task_name=task.name),
    }

    context["task"] = task_data
    context["history"] = await tasks_api.get(f"/{task.name}/history/")
    context["running_tasks"] = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")
    return templates.TemplateResponse(
        request=request,
        name="backups/restore/details.html",
        context=context,
    )
