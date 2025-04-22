"""Define routes for the archivers plugin."""

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
from app.sep.plugins.archives.deps import (
    ArchivesGeneratedTask,
    ArchivesTask,
    ArchivesUpdatedTask,
    get_archives_detail_context,
    get_archives_index_context,
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def archives_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_archives_index_context)],
) -> HTMLResponse:
    """Homepage of archives plugin."""
    return templates.TemplateResponse(
        request=request,
        name="archiver/index.html",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def archives_create(
    request: Request,
    task: ArchivesGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create new archives task."""
    logger.debug("Create archives task: %s", task)
    await task_api.post(
        "/",
        json=task.model_dump(),
    )
    task_path = request.url_for("archives_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def archives_detail(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_archives_detail_context)],
) -> HTMLResponse:
    """Retrieve archives task."""
    context["csrf_token"] = request.state.csrf_token
    return templates.TemplateResponse(
        request=request,
        name="archiver/details.html",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def archives_execute(
    request: Request,
    task: ArchivesTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
) -> RedirectResponse:
    """Execute archives task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={"eta": eta},
    )  # TODO: send meta form fields  # noqa: TD002, TD003
    task_path = request.url_for("archives_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/update",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def archives_update(
    request: Request,
    task_name: str,
    updated_task: ArchivesUpdatedTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Update archives task."""
    logger.debug("Updating archives task: %s", updated_task)
    await tasks_api.put(
        f"/{task_name}",
        json=updated_task.model_dump(),
    )
    return RedirectResponse(
        request.url_for("archives_detail", task_name=updated_task.name),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def archives_delete(
    task: ArchivesTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete archives task."""
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/archives", status_code=status.HTTP_303_SEE_OTHER)
