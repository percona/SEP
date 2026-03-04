# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define routes for the Tasks API."""

import json
import logging
import os
from collections import defaultdict
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy_celery_beat import PeriodicTask

from app.api.deps import CurrentUserID, IsAuthenticatedDep
from app.core.celery.deps import CeleryBeatSessionDep
from app.core.config import settings
from app.core.exceptions import HTTPBadRequestException, HTTPConflictException
from app.core.utils import utc_now
from app.core.utils.fields import NonEmptyStr
from app.tasks.celery import (
    celery,
    dispatch_queue_item,
    execute_task_queue,
    get_executor_for_task,
)
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.deps import (
    ExecutableTaskDep,
    get_executor,
    get_logs_offsets,
    PreparedTaskHistory,
    SessionDep,
    TaskDep,
    TaskExecutor,
    TaskHistoryWithTaskDep,
    validate_chain_task_names,
)
from app.tasks.execution.utils import parse_payload
from app.tasks.models import (
    FileMetadata,
    Task,
    TaskBackendEnum,
    TaskHistory,
    TaskHistoryResponse,
    TaskHistoryStatusEnum,
    TaskResponse,
    TaskStats,
    TaskWrite,
    TransformPayloadRequest,
)
from app.tasks.periodic.crud import PeriodicTaskManager
from app.tasks.periodic.models import PeriodicTaskCreate, PeriodicTaskResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


# TODO: Pagination  # noqa: TD002, TD003
@router.get("/", dependencies=[IsAuthenticatedDep], response_model=list[TaskResponse])
async def list_tasks(
    session: SessionDep, owner: str | None = None, target: str | None = None
) -> list[Task]:
    """List all active tasks."""
    logger.debug("Listing tasks")
    return await TaskManager.list_active(session=session, owner=owner, target=target)


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
    await PeriodicTaskManager.delete_where(
        celery_beat_session,
        PeriodicTaskManager.build_where_clause_by_task_names(task_name),
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
async def create_task(
    session: SessionDep, task: TaskWrite, current_user_id: CurrentUserID
) -> Task:
    """Create a new task."""
    logger.debug("Creating task %s", task.name)
    return await TaskManager.create(
        session,
        task,
        created_by=current_user_id,
    )


@router.put(
    "/{task_name}",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
async def update_task(
    session: SessionDep,
    existing_task: TaskDep,
    updated_task: TaskWrite,
    current_user_id: CurrentUserID,
) -> Task:
    """Update an existing task."""
    logger.debug("Updating task %s", existing_task.name)
    return await TaskManager.update(
        session, existing_task, updated_task, last_updated_by=current_user_id
    )


@router.get(
    "/{task_name}/periodic/",
    dependencies=[IsAuthenticatedDep],
    response_model=list[PeriodicTaskResponse],
)
async def list_periodic_tasks_by_task_name(
    celery_beat_session: CeleryBeatSessionDep, task: ExecutableTaskDep
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
    session: SessionDep,
    task: ExecutableTaskDep,
    periodic_task: PeriodicTaskCreate,
) -> PeriodicTask:
    """Create a new periodic task for the specified task name."""
    logger.debug("Creating periodic task %s", periodic_task)
    if periodic_task.execute_request and periodic_task.execute_request.chain_task_names:
        await validate_chain_task_names(
            session, periodic_task.execute_request.chain_task_names, task.name
        )
    kwargs = json.loads(periodic_task.kwargs)
    kwargs["task_name"] = task.name
    if not periodic_task.name:
        periodic_task.name = f"run_{task.name}_{periodic_task.period}_{hash(periodic_task.kwargs)}".replace(
            " ", "_"
        )
    kwargs["periodic_task_name"] = periodic_task.name
    return await PeriodicTaskManager.create(
        celery_beat_session, periodic_task, kwargs=json.dumps(kwargs)
    )


@router.post(
    "/execute/{task_name}",
    dependencies=[IsAuthenticatedDep],
    response_model=TaskHistoryResponse,
)
async def execute_task_name(
    session: SessionDep,
    queue_item: PreparedTaskHistory,
    task_name: str,
) -> TaskHistory:
    """Send a task for execution."""
    logger.debug(
        "Dispatching task %s at %s",
        task_name,
        queue_item.execution_request.eta or utc_now(),
    )

    root_task = await TaskManager.get_root_task(session, queue_item.task)
    executor = get_executor_for_task(root_task)
    if queue_item.execution_request.target not in executor.get_hosts():
        raise HTTPBadRequestException(
            f"Failed to dispatch task: Target {queue_item.execution_request.target!r}"
            f"is not available in {executor.__class__.__name__} for task {task_name!r}"
        )
    if queue_item.execution_request.eta:
        history_recorded = await TaskHistoryManager.save(session, queue_item)
        celery_task = execute_task_queue.apply_async(
            args=[history_recorded.id],
            eta=history_recorded.execution_request.eta,
            expires=history_recorded.execution_request.eta
            + timedelta(seconds=settings.CELERY.global_expire_seconds),
        )
        history_recorded.execution_request.tracking["celery_task_id"] = celery_task.id
        return await TaskHistoryManager.save(
            session, history_recorded, flag_modified_fields=["execution_request"]
        )
    return await dispatch_queue_item(queue_item, session)


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
    snippet_filename: NonEmptyStr | None = None,
) -> list[TaskHistory]:
    """Retrieve a task history by task name."""
    logger.debug("Requesting task history for %s", task)
    return await TaskHistoryManager.list_by_task_name(
        session=session,
        task_name=task,
        status=task_status,
        select_related_task=True,
        snippet_filename=snippet_filename,
    )


@router.get("/history/{task_history_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_task_history(
    task_history: TaskHistoryWithTaskDep,
) -> TaskHistoryResponse:
    """Retrieve a task history by id."""
    logger.debug("Requesting task history %s", task_history.id)
    return task_history


@router.get("/history/{task_history_id}/logs/", dependencies=[IsAuthenticatedDep])
async def stream_task_history_logs(
    executor: TaskExecutor,
    task_history: TaskHistoryWithTaskDep,
    offsets: Annotated[defaultdict[str, dict[str, int]], Depends(get_logs_offsets)],
    step: str | None = None,
) -> StreamingResponse:
    """Stream a task history's logs."""
    logger.debug("Requesting logs for task history %s", task_history.id)
    if task_history.status == TaskHistoryStatusEnum.PENDING:
        raise HTTPConflictException("Task history is pending.")
    if task_history.status == TaskHistoryStatusEnum.RUNNING:
        stream_logs_generator = (
            f"{log_line.model_dump_json()}\n" if log_line else ""
            async for log_line in executor.stream_logs(task_history, offsets)
        )
    else:
        stream_logs_generator = (
            log.model_dump_json() + "\n"
            for log in task_history.iter_logs(offsets, step=step)
        )
    return StreamingResponse(
        stream_logs_generator,
        media_type="application/json",
    )


@router.get(
    "/history/{task_history_id}/files/",
    dependencies=[IsAuthenticatedDep],
    response_model=dict[str, FileMetadata],
)
async def list_task_history_files(
    executor: TaskExecutor,
    task_history: TaskHistoryWithTaskDep,
) -> dict[str, FileMetadata]:
    """List files from a task history."""
    logger.debug("Requesting files for task history %s", task_history.id)
    if not task_history.status.is_finished():
        raise HTTPConflictException(f"Task history is {task_history.status}.")
    if task_history.task.output_files_path is None:
        raise HTTPBadRequestException(
            f"Task {task_history.task.name} does not have output_files_path set."
        )
    return await executor.list_files(task_history, task_history.task.output_files_path)


@router.get("/history/{task_history_id}/file/", dependencies=[IsAuthenticatedDep])
async def stream_task_history_file(
    executor: TaskExecutor,
    task_history: TaskHistoryWithTaskDep,
    path: str,
) -> StreamingResponse:
    """Stream a file from a task history."""
    logger.debug("Requesting file %s for task history %s", path, task_history.id)
    if not task_history.status.is_finished():
        raise HTTPConflictException(f"Task history is {task_history.status}.")
    if task_history.task.output_files_path is None:
        raise HTTPBadRequestException(
            f"Task {task_history.task.name} does not have output_files_path set."
        )
    return StreamingResponse(
        executor.stream_file(
            task_history,
            os.path.join(task_history.task.output_files_path, path.lstrip("/")),  # noqa: PTH118
        ),
        media_type="application/octet-stream",
    )


@router.post("/history/{task_history_id}/stop/", dependencies=[IsAuthenticatedDep])
async def stop_task_history(
    session: SessionDep, executor: TaskExecutor, task_history: TaskHistoryWithTaskDep
) -> TaskHistoryResponse:
    """Stop a task history."""
    logger.debug("Stopping task history %s", task_history.id)
    if task_history.status == TaskHistoryStatusEnum.PENDING:
        if celery_task_id := task_history.execution_request.tracking.get(
            "celery_task_id"
        ):
            logger.debug(
                "Cancelling pending task history %s with Celery task ID %s",
                task_history.id,
                celery_task_id,
            )
            celery.control.revoke(celery_task_id)
        return await TaskHistoryManager.delete(session, task_history)
    if task_history.status != TaskHistoryStatusEnum.RUNNING:
        raise HTTPBadRequestException(
            f"Cannot stop task history {task_history.id} ({task_history.task.name}): "
            f"task is not running (current status: {task_history.status})."
        )
    return await executor.stop_task(session, task_history)


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
    data: TransformPayloadRequest,
    backend: TaskBackendEnum = TaskBackendEnum.NOMAD,
) -> dict[str, Any]:
    """Transform a payload string into a dictionary."""
    if backend == TaskBackendEnum.PROXY:
        return parse_payload(data.payload, data.fmt)
    executor = get_executor(backend)
    return await executor.transform_payload(data.payload, data.fmt)
