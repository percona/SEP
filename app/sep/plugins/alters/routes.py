"""Define routes for the alters plugin."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.sep.config import sep_settings
from app.sep.deps import DefaultContext, IsAuthenticated, TaskAPI
from app.sep.plugins.alters.deps import (
    AltersGeneratedTask,
    AltersTask,
    get_alters_index_context,
)
from app.tasks.models import TriggerRequest

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
    data = task["data"]
    task_config = data["TaskGroups"][0]["Tasks"][0]["Config"]
    meta = data["TaskGroups"][0]["Tasks"][0]["Meta"]
    task_data = {
        "name": task["name"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
        "hostname": data["Constraints"][0]["RTarget"],
        "table": f"{meta['schema_name']}.{meta['table_name']}",
        "cmd": f"{task_config['command']} {' '.join(task_config['args'])}",
        "meta": meta,
    }
    context["task"] = task_data
    context["history"] = await tasks_api.get(f"/{task['name']}/history/")
    context["stats"] = await tasks_api.get(f"/stats/{task['name']}")
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
        f"/execute/{task['name']}"
    )  # TODO: send meta form fields  # noqa: TD002, TD003
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/trigger",
    dependencies=[IsAuthenticated],
    response_class=RedirectResponse,
)
async def alters_trigger(
    task: AltersTask,
    tasks_api: TaskAPI,
    trigger_data: Annotated[TriggerRequest, Form()],
) -> RedirectResponse:
    """Route the task to the appropriate queue based on the task name.

    :param task: The AltersTask object containing the task details.
    :type task: AltersTask
    :param tasks_api: The TaskAPI instance for interacting with the task API.
    :type tasks_api: TaskAPI
    :param trigger_data: The form data containing the parameters required to trigger
        the task.
    :type trigger_data: TriggerRequest
    :return: A redirection response to the alters list page after triggering the task.
    :rtype: RedirectResponse
    """
    logger.debug("triggering task %s", task["name"])
    await tasks_api.post(f"/trigger/{task['name']}", json=trigger_data.model_dump())

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
    await tasks_api.delete(f"/{task['name']}")
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)
