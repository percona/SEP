"""Define routes for the restores plugin."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.sep.config import sep_settings
from app.sep.deps import IsAuthenticated, IsCsrfValidated, TaskAPI
from app.sep.plugins.backup.restore.deps import (
    get_restores_index_context,
    RestoreGeneratedTask,
)

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
