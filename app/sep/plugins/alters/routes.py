"""Define routes for the alters plugin."""

import logging
import shlex
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import FutureDatetime

from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    HasNoConflictedRunningTasks,
    InventoryAPI,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.plugins.alters.deps import (
    AltersGeneratedTask,
    AltersTask,
    get_alters_index_context,
)
from app.sep.utils.jinja import syntax_highlight
from app.tasks.models import TaskHistoryStatusEnum

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


@router.get("/table/{table_id}/details", dependencies=[IsAuthenticated])
async def get_table_details(
    table_id: int,
    inventory_api: InventoryAPI,
    syntax_highlight_style: str | None = None,
) -> JSONResponse:
    """Get table details including create statement and keys."""
    try:
        table = await inventory_api.get(f"/tables/{table_id}")
        create = table["create"]
        if syntax_highlight_style:
            create = syntax_highlight(create, "sql", style=syntax_highlight_style)
        return JSONResponse(
            {
                "id": table["id"],
                "name": table["name"],
                "create": create,
                "keys": table["keys"],
            }
        )
    except HTTPException:
        return JSONResponse(
            {"error": "Failed to fetch table details"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def alters_create(
    request: Request,
    task: AltersGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create alter tasks - one for execution and one for dry run."""
    logger.debug("Create alters tasks: %s", task)

    # Create the execute task
    await task_api.post(
        "/generate/",
        json=task.model_dump(),
    )

    # Create the dry-run task
    dry_run_task = task.model_copy()
    dry_run_task.name = f"{task.name}-dry-run"
    # Replace --execute with --dry-run in the task arguments and add parent reference
    for command in dry_run_task.commands:
        if "args" in command:
            command["args"] = [
                arg.replace("--execute", "--dry-run") for arg in command["args"]
            ]
        if "meta" in command:
            command["meta"]["parent"] = task.name

    await task_api.post(
        "/generate/",
        json=dry_run_task.model_dump(),
    )

    # Redirect to the execute task detail page
    task_path = request.url_for("alters_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
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
        "cmd": f"{task_config['command']} {shlex.join(task_config['args'])}",
        "meta": meta,
        "delete_url": request.url_for("alters_delete", task_name=task.name),
        "dry_run_url": request.url_for(
            "alters_execute", task_name=task.name + "-dry-run"
        ),
    }

    # If the task has a parent, redirect to the parent task detail page
    if task_data["meta"].get("parent"):
        task_path = request.url_for(
            "alters_detail", task_name=task_data["meta"]["parent"]
        )
        return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)

    context["task"] = task_data
    # TODO(yan): Refactor/reuse like with get_tasks_context  # noqa: TD003
    context["history"] = await tasks_api.get(f"/{task.name}/history/")
    context["history_dry_run"] = await tasks_api.get(f"/{task.name}-dry-run/history/")
    context["running_tasks"] = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["running_tasks"] += await tasks_api.get(
        f"/{task.name}-dry-run/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")
    return templates.TemplateResponse(
        request=request,
        name="alters/details.html",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated, HasNoConflictedRunningTasks],
    response_class=RedirectResponse,
)
async def alters_execute(
    request: Request,
    task: AltersTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
) -> RedirectResponse:
    """Execute alters task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={"eta": eta},
    )  # TODO: send meta form fields  # noqa: TD002, TD003
    task_path = request.url_for("alters_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def alters_delete(
    task: AltersTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete alters tasks."""
    await tasks_api.delete(f"/{task.name}")
    await tasks_api.delete(f"/{task.name}-dry-run")
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)
