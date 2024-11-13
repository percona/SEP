"""Define routes for the Tasks API."""

import logging

from fastapi import APIRouter
from sqlalchemy_celery_beat import PeriodicTask

from app.api.deps import IsAuthenticatedDep
from app.core.celery.deps import CeleryBeatSessionDep
from app.tasks.crud import PeriodicTaskManager, TaskManager
from app.tasks.deps import PeriodicTaskDep, SessionDep
from app.tasks.models import (
    PeriodicTaskResponse,
    PeriodicTaskUpdate,
)

router = APIRouter(prefix="/periodic", tags=["schedules"])

logger = logging.getLogger(__name__)


# TODO: Pagination  # noqa: TD002, TD003
@router.get(
    "/", dependencies=[IsAuthenticatedDep], response_model=list[PeriodicTaskResponse]
)
async def list_periodic_tasks(
    session: CeleryBeatSessionDep, tasks_session: SessionDep, owner: str | None = None
) -> list[PeriodicTask]:
    """List all periodic tasks."""
    if owner is None:
        return await PeriodicTaskManager.list(session=session)
    tasks_names = [
        task.name
        for task in await TaskManager.list_active(session=tasks_session, owner=owner)
    ]
    return await PeriodicTaskManager.list_by_task_names(session, *tasks_names)


@router.get("/{periodic_task_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_periodic_task(
    periodic_task: PeriodicTaskDep,
) -> PeriodicTaskResponse:
    """Retrieve a periodic task by ID."""
    return periodic_task


@router.put(
    "/{periodic_task_id}",
    dependencies=[IsAuthenticatedDep],
    response_model=PeriodicTaskResponse,
)
async def update_periodic_task(
    session: CeleryBeatSessionDep,
    existing_task: PeriodicTaskDep,
    updated_task: PeriodicTaskUpdate,
) -> PeriodicTask:
    """Update a periodic task."""
    logger.debug("Updating periodic task %s", existing_task.id)
    return await PeriodicTaskManager.update(session, existing_task, updated_task)


@router.delete(
    "/{periodic_task_id}",
    dependencies=[IsAuthenticatedDep],
)
async def delete_periodic_task(
    session: CeleryBeatSessionDep, periodic_task: PeriodicTaskDep
) -> PeriodicTaskResponse:
    """Delete a periodic task."""
    logger.debug("Deleting periodic task %s", periodic_task)
    return await PeriodicTaskManager.delete(session, periodic_task)
