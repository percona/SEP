"""Define routes for the backups plugin."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import FutureDatetime

from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    HasNoConflictedRunningTasks,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.plugins.backup_mongo.deps import (
    BackupGeneratedTask,
    BackupsTask,
    get_backups_index_context,
)
from app.tasks.models import TaskHistoryStatusEnum

from .restore.routes import router as restore_router

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


router.include_router(restore_router, prefix="/restores", tags=["restores"])


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def pbm_backups_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_backups_index_context)],
) -> HTMLResponse:
    """Homepage of PBM backup mongo plugin."""
    return templates.TemplateResponse(
        request=request,
        name="backup_mongo/backup/index.html",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def pbm_backups_create(
    request: Request,
    task: BackupGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create new backups task."""
    logger.debug("Create backups task: %s", task)

    # Create the config task
    await task_api.post(
        "/",
        json=task.model_dump(),
    )

    # Create a logical backup task
    logical_task = task.model_copy()
    logical_task.data["backup_type"] = "pbm_logical"
    logical_task.name = f"{task.name}-logical"
    logical_task.data["parent"] = task.name
    logical_task.data["payload"] = logical_task.data["payload"].replace(
        "pbm_config", "pbm_logical"
    )

    await task_api.post(
        "/",
        json=logical_task.model_dump(),
    )

    # Create a physical backup task
    physical_task = task.model_copy()
    physical_task.data["backup_type"] = "pbm_physical"
    physical_task.name = f"{task.name}-physical"
    physical_task.data["parent"] = task.name
    physical_task.data["payload"] = logical_task.data["payload"].replace(
        "pbm_logical", "pbm_physical"
    )

    await task_api.post(
        "/",
        json=physical_task.model_dump(),
    )

    # Create a physical backup task
    status_task = task.model_copy()
    status_task.data["backup_type"] = "pbm_status"
    status_task.name = f"{task.name}-status"
    status_task.data["parent"] = task.name
    status_task.data["payload"] = logical_task.data["payload"].replace(
        "pbm_physical", "pbm_status"
    )

    await task_api.post(
        "/",
        json=status_task.model_dump(),
    )

    task_path = request.url_for("pbm_backups_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def pbm_backups_detail(
    task: BackupsTask,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve backups task."""
    data = task.data

    # If the task has a parent, redirect to the parent task detail page
    if data.get("parent"):
        task_path = request.url_for("pbm_backups_detail", task_name=data.get("parent"))
        return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)

    meta = data["meta"]
    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "hostname": meta["target"],
        "meta": meta,
        "backup_type": data["backup_type"],
        "logical_backup_url": request.url_for(
            "pbm_backups_execute", task_name=task.name + "-logical"
        ),
        "physical_backup_url": request.url_for(
            "pbm_backups_execute", task_name=task.name + "-physical"
        ),
    }

    context["task"] = task_data
    context["history"] = await tasks_api.get(f"/{task.name}/history/")
    context["history_logical"] = await tasks_api.get(f"/{task.name}-logical/history/")
    context["history_physical"] = await tasks_api.get(f"/{task.name}-physical/history/")
    context["running_tasks"] = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["running_tasks"] += await tasks_api.get(
        f"/{task.name}-logical/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    context["running_tasks"] += await tasks_api.get(
        f"/{task.name}-physical/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")

    # get latest status
    pbm_status_tasks = await tasks_api.get(f"/{task.name}-status/history/")
    try:
        tracking = pbm_status_tasks[0]["execution_request"]["tracking"]
        context["latest_status"] = tracking["task_logs"]["run-script"]["stdout"]
    except (IndexError, KeyError):
        context["latest_status"] = None

    return templates.TemplateResponse(
        request=request,
        name="backup_mongo/backup/details.html",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated, HasNoConflictedRunningTasks],
    response_class=RedirectResponse,
)
async def pbm_backups_execute(
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
    task_path = request.url_for("pbm_backups_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def pbm_backups_delete(
    request: Request,
    task: BackupsTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete backups task."""
    await tasks_api.delete(f"/{task.name}")
    await tasks_api.delete(f"/{task.name}-logical")
    task_path = request.url_for("pbm_backups_index")
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)
