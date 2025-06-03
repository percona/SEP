"""Define routes for the checksums plugin."""

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
from app.sep.plugins.checksums.deps import (
    ChecksumsGeneratedTask,
    ChecksumsTask,
    get_checksums_index_context,
)
from app.tasks.entity import decode_selection
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def checksums_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_checksums_index_context)],
) -> HTMLResponse:
    """Homepage of checksums plugin."""
    context["csrf_token"] = request.state.csrf_token
    return templates.TemplateResponse(
        request=request,
        name="checksums/index.html",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def checksums_create(
    request: Request,
    task: ChecksumsGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create an checksum task."""
    logger.debug("Create checksums task: %s", task)
    await task_api.post(
        "/generate/",
        json=task.model_dump(),
    )

    task_path = request.url_for("checksums_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def checksums_detail(
    task: ChecksumsTask,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve checksums task."""
    data = task.data
    decoded_entities = decode_selection(task.anonymize)
    task_config = data["TaskGroups"][0]["Tasks"][0]["Config"]
    meta = data["TaskGroups"][0]["Tasks"][0]["Meta"]
    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "hostname": data["Constraints"][0]["RTarget"],
        "cmd": f"{task_config['command']} {' '.join(task_config['args'])}",
        "meta": meta,
        "entities": {entity.name: entity.value for entity in decoded_entities},
        "delete_url": request.url_for("checksums_delete", task_name=task.name),
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
        name="checksums/details.html",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated, HasNoConflictedRunningTasks],
    response_class=RedirectResponse,
)
async def checksums_execute(
    task: ChecksumsTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
) -> RedirectResponse:
    """Execute checksums task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={"eta": eta},
    )  # TODO: send meta form fields  # noqa: TD002, TD003
    return RedirectResponse("/checksums", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def checksums_delete(
    task: ChecksumsTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete checksums task."""
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/checksums", status_code=status.HTTP_303_SEE_OTHER)
