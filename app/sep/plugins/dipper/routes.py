"""Define routes for the dipper plugin."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import FutureDatetime

from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.plugins.dipper.deps import (
    AppGeneratedTask,
    AppTask,
    get_app_index_context,
)
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def app_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_app_index_context)],
) -> HTMLResponse:
    """Homepage of dipper plugin."""
    context["csrf_token"] = request.state.csrf_token
    return templates.TemplateResponse(
        request=request,
        name="dipper/index.html",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def app_create(
    request: Request,
    task: AppGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create a task."""
    logger.debug("Create task: %s", task)
    await task_api.post(
        "/",
        json=task.model_dump(),
    )
    task_path = request.url_for("task_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def task_detail(
    task: AppTask,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve task."""
    data = task.data
    meta = data.get("meta", {})
    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": task.created_by,
        "last_updated_by": task.last_updated_by,
        "hostname": meta.get("target", ""),
        "cmd": f"{meta.get('command', '')} {meta.get('args', '')}",
        "meta": meta,
        "delete_url": request.url_for("task_delete", task_name=task.name),
        "alert_on_fail": task.alert_on_fail,
        "is_edit_enabled": not task.protected,
    }
    context["task"] = task_data
    # TODO(yan): Refactor/reuse like with get_tasks_context  # noqa: TD003
    context["history"] = await tasks_api.get(f"/{task.name}/history/")
    context["running_tasks"] = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")
    return templates.TemplateResponse(
        request=request,
        name="dipper/details.html",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def task_execute(
    request: Request,
    task: AppTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
) -> RedirectResponse:
    """Execute a task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={"eta": eta},
    )  # TODO: send meta form fields  # noqa: TD002, TD003
    task_path = request.url_for("task_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def task_delete(
    task: AppTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete a task."""
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/dipper", status_code=status.HTTP_303_SEE_OTHER)
