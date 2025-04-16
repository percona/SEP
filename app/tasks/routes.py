"""Define routes for the Tasks API."""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy_celery_beat import PeriodicTask

from app.api.deps import IsAuthenticatedDep
from app.core.celery.deps import CeleryBeatSessionDep
from app.core.exceptions import HTTPBadRequestException
from app.tasks.celery import execute_task_queue
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.deps import (
    CreatedTaskHistory,
    SessionDep,
    TaskDep,
    TaskExecutor,
)
from app.tasks.models import (
    Task,
    TaskHistory,
    TaskHistoryResponse,
    TaskHistoryStatusEnum,
    TaskLog,
    TaskResponse,
    TaskStats,
    TaskWrite,
    TransformPayloadRequest,
)
from app.tasks.periodic.config import periodic_tasks_settings
from app.tasks.periodic.crud import PeriodicTaskManager
from app.tasks.periodic.models import PeriodicTaskCreate, PeriodicTaskResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


# TODO: Pagination  # noqa: TD002, TD003
@router.get("/", dependencies=[IsAuthenticatedDep], response_model=list[TaskResponse])
async def list_tasks(session: SessionDep, owner: str | None = None) -> list[Task]:
    """List all active tasks."""
    logger.debug("Listing tasks")
    return await TaskManager.list_active(session=session, owner=owner)


@router.delete(
    "/{task_name}",
    dependencies=[IsAuthenticatedDep],
    response_model=TaskResponse,
)
async def delete_task(
    session: SessionDep, celery_beat_session: CeleryBeatSessionDep, task_name: str
) -> Task:
    """Delete a task."""
    logger.debug("Deleting task %s", task_name)
    # TODO(yan): Delete for real
    # SEP-170
    task = await TaskManager.delete_by_name(session=session, name=task_name)
    await PeriodicTaskManager.perform_action_by_task_names(
        celery_beat_session, periodic_tasks_settings.ON_ORPHAN, task_name
    )
    return task


@router.get(
    "/{task_name}", dependencies=[IsAuthenticatedDep], response_model=TaskResponse
)
async def get_task(task: TaskDep) -> Task:
    """Retrieve a task by its name."""
    return task


@router.post(
    "/",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
async def create_task(session: SessionDep, task: TaskWrite) -> Task:
    """Create a new task."""
    logger.debug("Creating task %s", task.name)
    return await TaskManager.create(session, task)


@router.put(
    "/{task_name}",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
async def update_task(
    session: SessionDep, existing_task: TaskDep, updated_task: TaskWrite
) -> Task:
    """Update an existing task."""
    logger.debug("Updating task %s", existing_task.name)
    return await TaskManager.update(session, existing_task, updated_task)


@router.get(
    "/{task_name}/periodic/",
    dependencies=[IsAuthenticatedDep],
    response_model=list[PeriodicTaskResponse],
)
async def list_periodic_tasks_by_task_name(
    celery_beat_session: CeleryBeatSessionDep, task: TaskDep
) -> list[PeriodicTask]:
    """List periodic tasks by task name."""
    return await PeriodicTaskManager.list_by_task_names(celery_beat_session, task.name)


@router.post(
    "/{task_name}/periodic/",
    dependencies=[IsAuthenticatedDep],
    response_model=PeriodicTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_periodic_task_for_task_name(
    celery_beat_session: CeleryBeatSessionDep,
    task: TaskDep,
    periodic_task: PeriodicTaskCreate,
) -> PeriodicTask:
    """Create a new periodic task for the specified task name."""
    logger.debug("Creating periodic task %s", periodic_task)
    kwargs = json.loads(periodic_task.kwargs)
    kwargs["task_name"] = task.name
    if not periodic_task.name:
        periodic_task.name = f"run_{task.name}_{periodic_task.period}_{hash(periodic_task.kwargs)}".replace(
            " ", "_"
        )
    return await PeriodicTaskManager.create(
        celery_beat_session, periodic_task, kwargs=json.dumps(kwargs)
    )


@router.post(
    "/execute/{task_name}",
    dependencies=[IsAuthenticatedDep],
    response_class=JSONResponse,
)
async def execute_task_name(
    task_name: str,
    history_recorded: CreatedTaskHistory,
) -> TaskHistoryResponse:
    """Send a task for execution."""
    logger.debug(
        "Executing task %s at %s", task_name, history_recorded.execution_request.eta
    )
    execute_task_queue.apply_async(
        args=[history_recorded.id], eta=history_recorded.execution_request.eta
    )
    return history_recorded


@router.get("/history/", dependencies=[IsAuthenticatedDep])
async def list_task_history(
    session: SessionDep,
    task_status: Annotated[TaskHistoryStatusEnum | None, Query(alias="status")] = None,
) -> list[TaskHistoryResponse]:
    """Create a new task."""
    logger.debug("Listing task history")
    return await TaskHistoryManager.list(
        session, select_related=(TaskHistory.task,), status=task_status
    )


@router.get(
    "/{task}/history/",
    dependencies=[IsAuthenticatedDep],
    response_model=list[TaskHistoryResponse],
)
async def get_task_history(
    session: SessionDep,
    task: str,
    task_status: Annotated[TaskHistoryStatusEnum | None, Query(alias="status")] = None,
) -> list[TaskHistory]:
    """Retrieve a task history by task name."""
    logger.debug("Requesting task history for %s", task)
    return await TaskHistoryManager.list_by_task_name(
        session=session,
        task_name=task,
        status=task_status,
        select_related_task=True,
    )


@router.get("/history/{task_history_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_task_history(
    session: SessionDep,
    task_history_id: int,
) -> TaskHistoryResponse:
    """Retrieve a task history by id."""
    logger.debug("Requesting task history %s", task_history_id)
    return await TaskHistoryManager.get_or_404(
        session=session,
        select_related=(TaskHistory.task,),
        id=task_history_id,
    )


@router.get("/history/{task_history_id}/logs/", dependencies=[IsAuthenticatedDep])
async def stream_task_history_logs(
    session: SessionDep, executor: TaskExecutor, task_history_id: int
) -> StreamingResponse:
    """Stream a task history's logs."""
    logger.debug("Requesting logs for task history %s", task_history_id)
    task_history = await TaskHistoryManager.get_or_404(
        session=session,
        id=task_history_id,
    )
    if task_history.status == TaskHistoryStatusEnum.PENDING:
        raise HTTPBadRequestException("Task history is pending.")
    if task_history.status == TaskHistoryStatusEnum.RUNNING:
        stream_logs_generator = (
            f"{log_line.model_dump_json()}\n" if log_line else ""
            async for log_line in executor.stream_logs(task_history)
        )
    else:
        stream_logs_generator = (
            f"{TaskLog(step=step, type=log_type, msg=log[log_type]).model_dump_json()}\n"
            for step, log in task_history.execution_request.tracking.get(
                "task_logs", {}
            ).items()
            for log_type in ("stdout", "stderr")
        )
    return StreamingResponse(
        stream_logs_generator,
        media_type="application/json",
    )


@router.post(
    "/history/", dependencies=[IsAuthenticatedDep], status_code=status.HTTP_201_CREATED
)
async def create_task_history(session: SessionDep, task: TaskHistory) -> TaskHistory:
    """Create a new task history."""
    logger.debug("Creating task history %s", task.name)
    return await TaskHistoryManager.save(session, task)


@router.get("/stats/{task}", dependencies=[IsAuthenticatedDep])
async def get_task_stats(session: SessionDep, task: str) -> TaskStats:
    """Calculate the statistics for the task."""
    logger.debug("Requesting task stats for %s", task)
    return TaskStats(
        tasks=await TaskHistoryManager.list_by_task_name(
            session=session,
            task_name=task,
            select_related_task=True,
        ),
    )


@router.get("/hosts/", dependencies=[IsAuthenticatedDep])
async def get_executor_hosts(executor: TaskExecutor) -> dict[str, str]:
    """Return the executor hosts from the executor."""
    return executor.get_hosts()


@router.post("/transform/", dependencies=[IsAuthenticatedDep])
async def transform_payload(
    executor: TaskExecutor,
    data: TransformPayloadRequest,
) -> dict[str, Any]:
    """Transform a payload string into a dictionary."""
    return await executor.transform_payload(data.payload, data.fmt)
