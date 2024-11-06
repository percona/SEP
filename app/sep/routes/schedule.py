"""Define routes for scheduling tasks"""
import pdb
import logging
from typing import Annotated
from fastapi import APIRouter, Form, status

from fastapi.responses import RedirectResponse
from app.sep.deps import IsAuthenticated, TaskAPI
from app.tasks.models import TaskScheduleRequest
logger = logging.getLogger(__name__)

router = APIRouter()

@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated],
)
async def schedule_task(
    task_name: str,
    tasks_api: TaskAPI,
    schedule_data: Annotated[TaskScheduleRequest, Form()],
) -> RedirectResponse:
    """Schdule task."""
    logger.debug("scheduling task %s, %s,", task_name, schedule_data)
    await tasks_api.post(f"/schedules/{task_name}", json=schedule_data.model_dump())

    return RedirectResponse("/tasks", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/cancel/{periodic_task_id}",
    dependencies=[IsAuthenticated],
    response_class=RedirectResponse,
)
async def cancel_periodic_task(
    periodic_task_id: str,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Cancel Periodic task."""
    logger.debug("Canceling Periodic task %s", periodic_task_id)
    await tasks_api.delete(f"/schedules/{periodic_task_id}")
    return RedirectResponse("/tasks", status_code=status.HTTP_303_SEE_OTHER)
