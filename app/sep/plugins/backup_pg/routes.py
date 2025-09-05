"""Define routes for the backups plugin."""

import logging
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import FutureDatetime

from app.inventory.models import ServiceTypeEnum
from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    HasNoConflictedRunningTasks,
    InventoryAPI,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.plugins.backup_pg.deps import (
#    BackupGeneratedTask,
#    BackupsTask,
    get_backups_index_context,
#    parse_backup_task_data,
)
from app.sep.plugins.backup_pg.models import BackupType
from app.tasks.anonymizer import PIIEntity
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES

@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def backups_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_backups_index_context)],
) -> HTMLResponse:
    """Homepage of PG backups plugin."""
    return templates.TemplateResponse(
        request=request,
        name="backup_pg/index.html",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def backups_create(
    request: Request,
    task: BackupGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create new backups task."""
    logger.debug("Create backups task: %s", task)
    await task_api.post(
        "/",
        json=task.model_dump(),
    )
    task_path = request.url_for("backups_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003
