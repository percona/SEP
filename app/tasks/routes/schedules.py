"""Define routes for the Tasks API."""

import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.api.deps import IsAuthenticatedDep
from app.tasks.celery.scheduler import remove_periodic_task, setup_periodic_task
from app.tasks.crud import PeriodicTaskManager
from app.tasks.deps import SessionDep, TaskConfig
from app.tasks.models import (
    CrontabPeriod,
    PeriodicTask,
    PeriodicTaskResponse,
    TaskExecutionRequest,
    TaskScheduleRequest,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])


logger = logging.getLogger(__name__)


@router.post("/{task_name}", dependencies=[IsAuthenticatedDep])
async def create_periodic_task(
    session: SessionDep,
    task_name: str,
    config: TaskConfig,
    schedule_data: TaskScheduleRequest = None,
) -> PeriodicTask:
    """Create a new PeriodicTask."""
    logger.debug("Creating periodic Task %s", schedule_data)

    try:
        crontab_period = CrontabPeriod.from_str(schedule_data.period)
    except ValueError as e:
        logger.debug("Crontab Error %s", e)
        raise HTTPException(status.HTTP_400_BAD_REQUEST) from None

    periodic_task = PeriodicTask(
        task_id=config.id,
        execute_request=TaskExecutionRequest(
            task=task_name,
            target=schedule_data.meta.get("target", "all"),
            meta=schedule_data.meta,
            payload=schedule_data.payload,
            tracking={"evaluation_id": ""},
        ),
        period=crontab_period.to_str(),
    )

    saved_periodic_task = await PeriodicTaskManager.save(session, periodic_task)

    await setup_periodic_task(saved_periodic_task)

    return saved_periodic_task


@router.get(
    "/{task}",
    dependencies=[IsAuthenticatedDep],
    response_model=list[PeriodicTask],
)
async def get_periodic_tasks(session: SessionDep, task: str) -> list[PeriodicTask]:
    """Retrieve a periodic tasks by task name."""
    logger.debug("Requesting periodic tasks for %s", task)
    return await PeriodicTaskManager.list_by_task_name(
        session=session,
        task_name=task,
        select_related_task=True,
    )


@router.get(
    "/",
    dependencies=[IsAuthenticatedDep],
    response_model=list[PeriodicTaskResponse],
)
async def get_periodic_tasks_with_owner(
    session: SessionDep, owner: str | None = None
) -> list[PeriodicTask]:
    """Retrieve a periodic tasks by task name."""
    logger.debug("Requesting periodic tasks for %s", owner)
    return await PeriodicTaskManager.list_active(
        session=session,
        owner=owner,
    )


@router.delete(
    "/{periodic_task_id}",
    dependencies=[IsAuthenticatedDep],
    response_class=JSONResponse,
)
async def delete_periodic_task(session: SessionDep, periodic_task_id: str) -> dict:
    """Delete periodic task from DB and ReadBeat."""
    periodic_task = await PeriodicTaskManager.get_or_404(session, id=periodic_task_id)

    logger.debug("Canceling periodic task %s", periodic_task)
    canceled_periodic_task = await PeriodicTaskManager.delete(session, periodic_task)

    await remove_periodic_task(session=session, periodic_task=canceled_periodic_task)

    return {"id": canceled_periodic_task.id, "deleted": True}
