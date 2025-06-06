"""Define route for stopping tasks."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from starlette.responses import RedirectResponse

from app.sep.deps import get_task_history, IsAuthenticated, IsCsrfValidated, TaskAPI
from app.sep.middleware import messages
from app.tasks.models import TaskHistoryResponse, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{task_history_id}", dependencies=[IsAuthenticated, IsCsrfValidated])
async def stop_task_execution(
    request: Request,
    task_history: Annotated[TaskHistoryResponse, Depends(get_task_history)],
    tasks_api: TaskAPI,
    referer: Annotated[str, Header()] = "/",
) -> RedirectResponse:
    """Stop a task history."""
    logger.debug("Stopping task history %s", task_history.id)
    task_history = await tasks_api.post(f"/history/{task_history.id}/stop/")
    task_name = task_history["task"]["name"]
    task_status = task_history["status"]
    if task_status == TaskHistoryStatusEnum.STOPPED:
        messages.success(request, f"Task '{task_name}' has been stopped successfully.")
    else:
        messages.success(request, f"Task '{task_name}' canceled before execution.")
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)
