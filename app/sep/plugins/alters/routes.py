"""Define routes for the alters plugin."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    IsAuthenticated,
    task_history_logs_event_stream,
    TaskAPI,
)
from app.sep.plugins.alters.deps import (
    AltersGeneratedTask,
    AltersTask,
    get_alters_index_context,
    get_alters_task_history,
)
from app.tasks.models import TaskHistory

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alters_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_alters_index_context)],
) -> HTMLResponse:
    """Homepage of alters plugin."""
    return templates.TemplateResponse(
        request=request,
        name="alters/index.html",
        context=context,
    )


@router.post("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alters_create(
    task: AltersGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create an alter task."""
    logger.debug("Create alters task: %s", task)
    # TODO: validate response  # noqa: TD002, TD003
    await task_api.post(
        "/generate/",
        json=task.model_dump(),
    )  # TODO: Proper error for unique constraint  # noqa: TD002, TD003
    return RedirectResponse(
        "/alters",
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alters_detail(
    task: AltersTask,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve alters task."""
    data = task.data
    task_config = data["TaskGroups"][0]["Tasks"][0]["Config"]
    meta = data["TaskGroups"][0]["Tasks"][0]["Meta"]
    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "hostname": data["Constraints"][0]["RTarget"],
        "table": f"{meta['schema_name']}.{meta['table_name']}",
        "cmd": f"{task_config['command']} {' '.join(task_config['args'])}",
        "meta": meta,
    }
    context["task"] = task_data
    context["history"] = await tasks_api.get(f"/{task.name}/history/")
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")
    return templates.TemplateResponse(
        request=request,
        name="alters/details.html",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated],
    response_class=RedirectResponse,
)
async def alters_execute(
    task: AltersTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Execute alters task."""
    await tasks_api.post(
        f"/execute/{task.name}"
    )  # TODO: send meta form fields  # noqa: TD002, TD003
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated],
    response_class=RedirectResponse,
)
async def alters_delete(
    task: AltersTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete alters task."""
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logs/{task_history_id}", dependencies=[IsAuthenticated])
async def alters_logs_event_stream(
    task_history: Annotated[TaskHistory, Depends(get_alters_task_history)],
    tasks_api: TaskAPI,
) -> StreamingResponse:
    """Stream an alters task history's logs as server-sent events."""
    return StreamingResponse(
        task_history_logs_event_stream(tasks_api, task_history.id),
        media_type="text/event-stream",
    )
