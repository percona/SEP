"""Define routes for the Tasks API."""

import json
import logging

from fastapi import APIRouter, status
from sqlalchemy_celery_beat import PeriodicTask

from app.api.deps import IsAuthenticatedDep
from app.core.celery.deps import CeleryBeatSessionDep
from app.tasks.crud import TaskManager
from app.tasks.deps import get_executable_task_by_name, SessionDep
from app.tasks.models import (
    TaskOwner,
)
from app.tasks.periodic.crud import PeriodicTaskManager
from app.tasks.periodic.deps import PeriodicTaskDep
from app.tasks.periodic.models import (
    ExtendedPeriodicTaskResponse,
    PeriodicTaskResponse,
    PeriodicTaskUpdate,
)

router = APIRouter(prefix="/periodic", tags=["periodic", "schedule", "tasks"])

logger = logging.getLogger(__name__)


# TODO: Pagination  # noqa: TD002, TD003
@router.get(
    "/",
    dependencies=[IsAuthenticatedDep],
    response_model=list[ExtendedPeriodicTaskResponse],
)
async def list_periodic_tasks(
    session: CeleryBeatSessionDep,
    tasks_session: SessionDep,
    owner: TaskOwner | None = None,
    *,
    list_active: bool = False,
) -> list[PeriodicTask]:
    """List all periodic tasks."""
    if owner is None:
        tasks = await PeriodicTaskManager.list(session=session)
        for task in tasks:
            unique_task_name = json.loads(task.kwargs).get("task_name")
            task_detail = await TaskManager.retrieve_by_name(
                session=tasks_session, name=unique_task_name
            )
            task.owner = task_detail.owner
    else:
        tasks_names = [
            task.name
            for task in await TaskManager.list_active(
                session=tasks_session, owner=owner
            )
        ]
        tasks = await PeriodicTaskManager.list_by_task_names(session, *tasks_names)
        for task in tasks:
            task.owner = owner

    if list_active:
        tasks = [task for task in tasks if task.enabled]

    return tasks


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
    tasks_session: SessionDep,
    existing_task: PeriodicTaskDep,
    updated_task: PeriodicTaskUpdate,
) -> PeriodicTask:
    """Update a periodic task."""
    updated_kwargs = json.loads(updated_task.kwargs)
    existing_kwargs = json.loads(existing_task.kwargs)
    if (task_name := updated_kwargs.get("task_name")) != existing_kwargs["task_name"]:
        await get_executable_task_by_name(tasks_session, task_name)
    logger.debug("Updating periodic task %s", existing_task.id)
    return await PeriodicTaskManager.update(session, existing_task, updated_task)


@router.delete(
    "/{periodic_task_id}",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_periodic_task(
    session: CeleryBeatSessionDep, periodic_task: PeriodicTaskDep
) -> None:
    """Delete a periodic task."""
    logger.debug("Deleting periodic task %s", periodic_task)
    await PeriodicTaskManager.delete(session, periodic_task)
