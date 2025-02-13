"""Define routes for the alters plugin."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import FutureDatetime

from app.sep.config import sep_settings
from app.sep.deps import (
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.plugins.alters.deps import (
    AltersGeneratedTask,
    AltersTask,
    get_alters_detail_context,
    get_alters_index_context,
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alters_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_alters_index_context)],
) -> HTMLResponse:
    """Homepage of alters plugin."""
    context["csrf_token"] = request.state.csrf_token
    return templates.TemplateResponse(
        request=request,
        name="alters/index.html",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def alters_create(
    task: AltersGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create an alter task."""
    logger.debug("Create alters task: %s", task)
    await task_api.post(
        "/generate/",
        json=task.model_dump(),
    )
    return RedirectResponse(
        "/alters",
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alters_detail(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_alters_detail_context)],
) -> HTMLResponse:
    """Retrieve alters task."""
    context["csrf_token"] = request.state.csrf_token
    return templates.TemplateResponse(
        request=request,
        name="alters/details.html",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def alters_execute(
    task: AltersTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
) -> RedirectResponse:
    """Execute alters task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={"eta": eta},
    )  # TODO: send meta form fields  # noqa: TD002, TD003
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/update",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def alters_update(
    task_name: str,
    task_update: AltersGeneratedTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Update alters task."""
    logger.debug("Updating alters task: %s", task_update)
    await tasks_api.put(
        f"/generate/{task_name}",
        json=task_update.model_dump(),
    )
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def alters_delete(
    task: AltersTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete alters task."""
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)
