"""Define routes for scheduling tasks."""

import logging
from typing import Annotated

from fastapi import APIRouter, Form, Header, status
from fastapi.responses import RedirectResponse

from app.core.utils import deep_dict_update
from app.sep.deps import IsAuthenticated, IsCsrfValidated, TaskAPI
from app.sep.tasks import (
    EnhancedPeriodicTaskCreateRequest,
    PeriodicTaskRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/",
    dependencies=[IsAuthenticated, IsCsrfValidated],
)
async def create_periodic_task(
    tasks_api: TaskAPI,
    periodic_task: Annotated[EnhancedPeriodicTaskCreateRequest, Form()],
    referer: Annotated[str, Header()] = "/tasks",
) -> RedirectResponse:
    """Create periodic task."""
    periodic_task_data = periodic_task.model_dump(exclude_none=True, exclude={"task"})
    logger.debug("Scheduling task %s, %s,", periodic_task.task, periodic_task_data)
    await tasks_api.post(f"/{periodic_task.task}/periodic/", json=periodic_task_data)
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{periodic_task_id}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def delete_periodic_task(
    periodic_task_id: str,
    tasks_api: TaskAPI,
    referer: Annotated[str, Header()] = "/tasks",
) -> RedirectResponse:
    """Delete Periodic task."""
    logger.debug("Deleting Periodic task %s", periodic_task_id)
    await tasks_api.delete(f"/periodic/{periodic_task_id}")
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{periodic_task_id}/update", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def update_periodic_task(
    periodic_task_id: int,
    tasks_api: TaskAPI,
    updated_task: Annotated[PeriodicTaskRequest, Form()],
    referer: Annotated[str, Header()] = "/tasks",
) -> RedirectResponse:
    """Update periodic task."""
    updated_task_data = updated_task.model_dump(exclude_unset=True)
    if updated_task_data:
        periodic_task_data = await tasks_api.get(f"/periodic/{periodic_task_id}")
        deep_dict_update(periodic_task_data, updated_task_data)
        await tasks_api.put(f"/periodic/{periodic_task_id}", json=periodic_task_data)
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)
