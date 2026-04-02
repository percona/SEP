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

"""Define Celery tasks and utilities for the Tasks app.

This module defines functions for executing tasks asynchronously via Celery,
along with utility functions to process queue items.
"""

import json
import logging
from datetime import timedelta
from hashlib import sha256
from typing import Any

from celery import Task
from celery.app.task import Context
from celery.signals import task_revoked
from fastapi.encoders import jsonable_encoder
from nomad.api.exceptions import BaseNomadException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, or_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.celery import celery
from app.core.alerts.config import alert_service
from app.core.alerts.models import AlertSeverity
from app.core.db.utils import (
    func_json_extract,
    prepare_unsafe_value_for_json_comparison,
)
from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
)
from app.core.utils import utc_now
from app.tasks.config import tasks_settings
from app.tasks.crud import DispatchLockManager, TaskHistoryManager, TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import (
    get_executable_task_by_name,
    get_executor,
    prepare_task_history,
)
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    DispatchLock,
    SYSTEM_USER,
    TaskHistory,
    TaskHistoryStatusEnum,
)
from app.tasks.periodic.models import PeriodicTaskExecuteRequest

logger = logging.getLogger(__name__)


@task_revoked.connect
def task_revoked_handler(*, request: Context, expired: bool, **kwargs: Any) -> None:
    """Handle task revocation by logging the event."""
    queue_id = request.args[0] if request.args else request.kwargs.get("queue_id")
    if (
        request.get("task") == "app.tasks.celery.execute_task_queue"
        and queue_id
        and expired
    ):
        logger.info("Deleting expired TaskHistory %s", queue_id)
        celery.loop.run_until_complete(delete_task_history(queue_id))


@celery.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": celery.conf.max_retries},
)
def execute_task_queue(self: Task, queue_id: int) -> dict[str, Any]:
    """Trigger a Celery task by executing a queue item.

    :param self: The Celery task instance.
    :type self: Task
    :param queue_id: The ID of the queue item to trigger.
    :type queue_id: int
    :return: The data of the processed TaskHistory.
    :rtype: dict[str, Any]
    """
    logger.info("Executing task with queue_id: %s", queue_id)
    queue_item = celery.loop.run_until_complete(get_task_history(queue_id))
    return jsonable_encoder(
        celery.loop.run_until_complete(dispatch_queue_item(queue_item))
    )


@celery.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": celery.conf.max_retries},
)
def execute_task_by_name(
    self: Task,
    task_name: str,
    periodic_task_name: str | None = None,
    execution_data: PeriodicTaskExecuteRequest | None = None,
) -> dict[str, Any]:
    """Define Celery task to execute a SEP task by name.

    :param self: The Celery task instance.
    :type self: Task
    :param task_name: The name of the task to execute.
    :type task_name: int | None
    :param periodic_task_name: The name of the periodic task, if available.
    :type periodic_task_name: str | None
    :param execution_data: Execution details and parameters, if any.
    :type execution_data: PeriodicTaskExecuteRequest | None
    :return: The data of the processed TaskHistory.
    :rtype: dict[str, Any]
    """
    task_history = celery.loop.run_until_complete(
        prepare_periodic_task_history(task_name, execution_data)
    )
    try:
        task_history = celery.loop.run_until_complete(dispatch_queue_item(task_history))
    except BaseNomadException:
        alert_msg = f"Failed to dispatch periodic task {periodic_task_name or task_name}: error getting a response from Nomad"
        logger.exception(alert_msg)
        if task_history.task.alert_on_fail:
            alert_data = {
                "summary": alert_msg,
                "source": f"{task_name}:{task_history.execution_request.target}",
                "severity": AlertSeverity.ERROR,
                "class": "task_dispatch_failure",
            }
            if periodic_task_name:
                alert_data["source"] = f"{periodic_task_name}:{alert_data['source']}"
            celery.loop.run_until_complete(alert_service.trigger(alert_data))
    return jsonable_encoder(task_history)


@celery.task
def sync_running_tasks() -> None:
    """Define Celery task to sync running tasks."""
    celery.loop.run_until_complete(sync_running_items())


@celery.task
def sync_task_history(task_history_id: int) -> None:
    """Define Celery task to sync a task history item.

    :param task_history_id: The unique identifier of the task history item to sync.
    :type task_history_id: int
    """
    logger.info("Syncing task history %s", task_history_id)
    celery.loop.run_until_complete(sync_queue_item(task_history_id))
    logger.info("Finished syncing task history %s", task_history_id)


async def delete_task_history(queue_id: int) -> None:
    """Delete a TaskHistory object by queue ID.

    :param queue_id: The unique identifier of the queue item to delete.
    :type queue_id: int
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        await TaskHistoryManager.delete_where(session, id=queue_id)


async def get_task_history(queue_id: int) -> TaskHistory:
    """Get TaskHistory object by queue ID.

    :param queue_id: The unique identifier of the queue item to retrieve.
    :type queue_id: int
    :return: The TaskHistory object.
    :rtype: TaskHistory
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        return await TaskHistoryManager.get_or_404(
            session, select_related=[TaskHistory.task], id=queue_id
        )


async def prepare_periodic_task_history(
    task_name: str, execution_data: PeriodicTaskExecuteRequest | None = None
) -> TaskHistory:
    """Prepare and record the history of a periodic task execution request.

    :param task_name: The name of the task to execute.
    :type task_name: str
    :param execution_data: Execution details and parameters, if any.
    :type execution_data: PeriodicTaskExecuteRequest | None
    :return: The logged TaskHistory entry.
    :rtype: TaskHistory
    """
    execution_data = (
        PeriodicTaskExecuteRequest.model_validate(execution_data)
        if execution_data
        else None
    )
    async_session = get_async_session_maker()
    async with async_session() as session:
        task = await get_executable_task_by_name(session, task_name)
        return prepare_task_history(
            task, executed_by=SYSTEM_USER, execution_data=execution_data
        )


async def dispatch_queue_item(
    queue_item: TaskHistory, session: AsyncSession | None = None
) -> TaskHistory:
    """Process an item from the history table.

    :param queue_item: The TaskHistory object to dispatch.
    :type queue_item: TaskHistory
    :param session: Optional SQLAlchemy asynchronous session to use for the operation.
    :type session: AsyncSession | None
    :return: The TaskHistory object post execution.
    :rtype: TaskHistory
    :raises HTTPException: If the queue item status is not PENDING,
        raises a 409 Conflict error.
    :raises HTTPBadRequestException: If the task backend is unsupported,
        raises a 400 Bad Request error.
    """
    if session is None:
        async_session = get_async_session_maker()
        async with async_session() as async_session:
            return await _dispatch_queue_item(queue_item, async_session)
    return await _dispatch_queue_item(queue_item, session)


async def _dispatch_queue_item(
    queue_item: TaskHistory, session: AsyncSession
) -> TaskHistory:
    if queue_item.status != TaskHistoryStatusEnum.PENDING:
        raise HTTPConflictException("Queue item is not in a pending state.")

    dispatch_lock_name = sha256(
        json.dumps(
            {
                "task_id": queue_item.task_id,
                "task": queue_item.execution_request.task,
                "target": queue_item.execution_request.target,
                "payload": queue_item.execution_request.payload,
                "meta": queue_item.execution_request.meta,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    lock_session_maker = get_async_session_maker()
    async with lock_session_maker() as lock_session:
        await DispatchLockManager.delete_where(
            lock_session,
            col(DispatchLock.created_at) < (utc_now() - timedelta(seconds=30)),
            name=dispatch_lock_name,
        )
        try:
            dispatch_lock = await DispatchLockManager.create(
                lock_session, DispatchLock(name=dispatch_lock_name)
            )
        except IntegrityError as exc:
            raise HTTPConflictException("Identical dispatch in progress.") from exc

    try:
        await _raise_if_identical_task_conflict(queue_item, session)
        task = await TaskManager.get_root_task(session, queue_item.task)
        executor = get_executor_for_task(task)
        return await executor.dispatch_task(session, queue_item, task)
    except Exception:
        logger.exception("Failed to dispatch queue item")
        raise
    finally:
        async with lock_session_maker() as async_session:
            await DispatchLockManager.delete(async_session, dispatch_lock)


async def _raise_if_identical_task_conflict(
    queue_item: TaskHistory, session: AsyncSession
) -> None:
    engine_name = session.get_bind().name
    meta_where_clauses = []
    if queue_item.execution_request.meta:
        meta_where_clauses = [
            func_json_extract(engine_name, TaskHistory.execution_request, "meta", field)
            == prepare_unsafe_value_for_json_comparison(engine_name, value)
            for field, value in queue_item.execution_request.meta.items()
        ]
    if identical_task := (
        await TaskHistoryManager.first(
            session,
            func_json_extract(engine_name, TaskHistory.execution_request, "task")
            == queue_item.execution_request.task,
            func_json_extract(engine_name, TaskHistory.execution_request, "target")
            == queue_item.execution_request.target,
            func_json_extract(engine_name, TaskHistory.execution_request, "payload")
            == queue_item.execution_request.payload,
            *meta_where_clauses,
            col(TaskHistory.status).in_(
                [TaskHistoryStatusEnum.PENDING, TaskHistoryStatusEnum.RUNNING]
            ),
            col(TaskHistory.id) != queue_item.id,
            task_id=queue_item.task_id,
        )
    ):
        raise HTTPConflictException(
            f"Identical queue item already running ({identical_task.id})."
        )


async def sync_running_items() -> None:
    """Sync running tasks in the task history.

    This function updates the `sync_in_progress_started_at` field for tasks that are
    either not currently in progress or have been in progress for longer than the
    configured SYNC_LOCK_TTL. It then dispatches the sync task for those tasks.
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        result = await TaskHistoryManager.update_where(
            session,
            {"sync_in_progress_started_at": func.now()},
            or_(
                col(TaskHistory.sync_in_progress_started_at).is_(None),
                col(TaskHistory.sync_in_progress_started_at)
                < (utc_now() - tasks_settings.SYNC_LOCK_TTL),
            ),
            returning=("id",),
            status=TaskHistoryStatusEnum.RUNNING,
        )
        args = [(item_id,) for item_id in result]
        if args:
            logger.debug("Dispatching sync of %d running tasks", len(args))
            chunk_size = 100
            sync_task_history.chunks(args, chunk_size).apply_async()


async def sync_queue_item(queue_id: int) -> TaskHistory:
    """Sync a task history item.

    :param queue_id: The unique identifier of the queue item to sync.
    :type queue_id: int
    :return: The TaskHistory object post sync.
    :rtype: TaskHistory
    :raises HTTPBadRequestException: If the task backend is unsupported,
        raises a 400 Bad Request error.
    """
    async_session = get_async_session_maker()
    async with async_session() as session:
        queue_item = await TaskHistoryManager.get_or_404(
            session,
            select_related=[TaskHistory.task],
            id=queue_id,
        )
        task = await TaskManager.get_root_task(session, queue_item.task)
    if queue_item.is_running:
        executor = get_executor_for_task(task)
        queue_item = await executor.sync_task_history(queue_item)
    queue_item.sync_in_progress_started_at = None
    async with async_session() as session:
        return await TaskHistoryManager.save(
            session, queue_item, flag_modified_fields=["execution_request"]
        )


def get_executor_for_task(task: Task) -> BaseExecutor:
    """Get the executor for a specific task.

    :param task: The task for which to get the executor.
    :type task: Task
    :return: The executor for the task.
    :rtype: BaseExecutor
    """
    try:
        return get_executor(task.backend)
    except ValueError:
        raise HTTPBadRequestException(
            f"Unsupported task backend: {task.backend}"
        ) from None
