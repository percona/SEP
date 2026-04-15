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

"""Define the connectivity check service logic."""

import asyncio
import json
import time
from pathlib import Path

from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.celery import dispatch_queue_item, get_executor_for_task
from app.tasks.connectivity.models import (
    ConnectivityCheckResponse,
    ConnectivityCheckWrite,
    ConnectivityServiceType,
    REQUIREMENTS_BY_SERVICE_TYPE,
)
from app.tasks.crud import TaskHistoryManager
from app.tasks.deps import get_executable_task_by_name
from app.tasks.models import (
    SYSTEM_USER,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLogType,
)

PAYLOAD_PATH = Path(__file__).parent / "payload.py"
POLL_INTERVAL = 2
FRESH_FETCH_MAX_ATTEMPTS = 3
FRESH_FETCH_INTERVAL = 0.5
RESULT_CACHE_TTL = 300

_result_cache: dict[
    tuple[str, ConnectivityServiceType], tuple[bool, str | None, float]
] = {}


def get_cached_result(
    target: str, service_type: ConnectivityServiceType
) -> tuple[bool, str | None] | None:
    """Return a cached connectivity check result, or ``None`` if expired or missing.

    :param target: The Nomad node name.
    :type target: str
    :param service_type: The database service type.
    :type service_type: ConnectivityServiceType
    :return: A tuple of ``(success, error)`` if cached and fresh, otherwise ``None``.
    :rtype: tuple[bool, str | None] | None
    """
    key = (target, service_type)
    entry = _result_cache.get(key)
    if entry is None:
        return None
    success, error, timestamp = entry
    if time.monotonic() - timestamp > RESULT_CACHE_TTL:
        del _result_cache[key]
        return None
    return success, error


def cache_result(
    target: str,
    service_type: ConnectivityServiceType,
    *,
    success: bool,
    error: str | None,
) -> None:
    """Cache a connectivity check result with the current timestamp.

    :param target: The Nomad node name.
    :type target: str
    :param service_type: The database service type.
    :type service_type: ConnectivityServiceType
    :param success: Whether the connectivity check succeeded.
    :type success: bool
    :param error: Error message if the check failed.
    :type error: str | None
    """
    _result_cache[(target, service_type)] = (success, error, time.monotonic())


async def check_connectivity(
    session: AsyncSession,
    request: ConnectivityCheckWrite,
) -> ConnectivityCheckResponse:
    """Dispatch a Nomad connectivity check and wait for the result.

    :param session: The async database session.
    :type session: AsyncSession
    :param request: The connectivity check request parameters.
    :type request: ConnectivityCheckWrite
    :return: The connectivity check result.
    :rtype: ConnectivityCheckResponse
    """
    task = await get_executable_task_by_name(session, "run-python")

    config = json.dumps(
        {
            "host": request.host,
            "port": request.port,
            "service_type": request.service_type,
        }
    )
    queue_item = TaskHistory(
        task_id=task.id,
        task=task,
        execution_request=TaskExecutionRequest(
            task=task.name,
            target=request.target,
            meta={
                "target": request.target,
                "config": config,
                "requirements": REQUIREMENTS_BY_SERVICE_TYPE[request.service_type],
            },
            payload=f"file://{PAYLOAD_PATH}",
            tracking={"evaluation_id": ""},
        ),
        status=TaskHistoryStatusEnum.PENDING,
        executed_by=SYSTEM_USER,
        anonymize_mask=0,
    )

    queue_item = await dispatch_queue_item(queue_item, session)
    if queue_item.id is None:
        raise RuntimeError("dispatch_queue_item returned a queue item without an ID")
    queue_item_id = queue_item.id

    executor = get_executor_for_task(task)
    elapsed = 0
    while (
        queue_item.status
        in (TaskHistoryStatusEnum.PENDING, TaskHistoryStatusEnum.RUNNING)
        and elapsed < request.timeout
    ):
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        queue_item = await executor.sync_task_history(queue_item)
        await TaskHistoryManager.save(
            session, queue_item, flag_modified_fields=["execution_request"]
        )

    if queue_item.status in (
        TaskHistoryStatusEnum.PENDING,
        TaskHistoryStatusEnum.RUNNING,
    ):
        return ConnectivityCheckResponse(
            success=False,
            error=f"Connectivity check timed out after {request.timeout}s",
            task_history_id=queue_item_id,
        )

    fresh_queue_item = await _fetch_fresh_task_history(session, queue_item_id)
    result = _parse_check_result(fresh_queue_item)
    cache_result(
        request.target,
        request.service_type,
        success=result.success,
        error=result.error,
    )
    return result


async def _fetch_fresh_task_history(
    session: AsyncSession, task_history_id: int
) -> TaskHistory:
    """Re-read the task history row from the database until its logs land.

    The polling loop's last successful ``sync_task_history`` populates the
    ``task_logs`` column of the DB row, but the in-memory
    ``TaskExecutionRequest`` Pydantic object attached to ``queue_item`` is
    NOT re-hydrated through a subsequent ``session.get``: the identity map
    returns the existing object and SQLAlchemy's refresh leaves nested JSON
    fields untouched. Expunge the row and fetch it again so a brand-new
    object is materialised from the row as it exists in the database.
    A small retry budget covers the narrow window where the final sync has
    not yet committed by the time the handler reaches this point.

    :param session: The async database session.
    :type session: AsyncSession
    :param task_history_id: The ID of the task history row to refresh.
    :type task_history_id: int
    :return: The freshest task history row available within the retry budget.
    :rtype: TaskHistory
    """
    task_history = await _expire_and_fetch(session, task_history_id)
    for _ in range(FRESH_FETCH_MAX_ATTEMPTS - 1):
        if _has_run_script_logs(task_history):
            return task_history
        await asyncio.sleep(FRESH_FETCH_INTERVAL)
        task_history = await _expire_and_fetch(session, task_history_id)
    return task_history


async def _expire_and_fetch(session: AsyncSession, task_history_id: int) -> TaskHistory:
    """Commit, expunge, and re-fetch the task history to bypass the cache.

    The executor's earlier ``sync_task_history`` mutates the in-memory
    ``TaskExecutionRequest`` Pydantic object, which SQLAlchemy's refresh
    does not fully re-hydrate for nested JSON columns. Commit to end the
    open snapshot, then expunge the row from the identity map so the next
    fetch does a genuine ``SELECT`` and builds a brand-new object.

    :param session: The async database session.
    :type session: AsyncSession
    :param task_history_id: The ID of the task history row to reload.
    :type task_history_id: int
    :return: A freshly-loaded task history row.
    :rtype: TaskHistory
    """
    await session.commit()
    cached = await TaskHistoryManager.get_or_404(session, id=task_history_id)
    session.expunge(cached)
    return await TaskHistoryManager.get_or_404(session, id=task_history_id)


def _has_run_script_logs(task_history: TaskHistory) -> bool:
    """Return whether ``task_history`` has any ``run-script`` step output.

    :param task_history: The task history record to inspect.
    :type task_history: TaskHistory
    :return: ``True`` if a non-empty stdout or stderr log exists for the
        ``run-script`` step, ``False`` otherwise.
    :rtype: bool
    """
    return any(log.msg for log in task_history.iter_logs(step="run-script"))


def _parse_check_result(task_history: TaskHistory) -> ConnectivityCheckResponse:
    """Extract connectivity result from task logs.

    :param task_history: The completed task history record.
    :type task_history: TaskHistory
    :return: The parsed connectivity check result.
    :rtype: ConnectivityCheckResponse
    """
    if task_history.id is None:
        raise RuntimeError("_parse_check_result called with unsaved TaskHistory")

    if task_history.status == TaskHistoryStatusEnum.FAILED:
        stderr = ""
        for log in task_history.iter_logs(step="run-script"):
            if log.type == TaskLogType.STDERR:
                stderr += log.msg or ""
        return ConnectivityCheckResponse(
            success=False,
            error=stderr or "Task failed",
            task_history_id=task_history.id,
        )

    stdout = ""
    for log in task_history.iter_logs(step="run-script"):
        if log.type == TaskLogType.STDOUT:
            stdout += log.msg or ""

    try:
        result = json.loads(stdout)
        return ConnectivityCheckResponse(
            success=result.get("success", False),
            error=result.get("error"),
            task_history_id=task_history.id,
        )
    except (json.JSONDecodeError, AttributeError):
        return ConnectivityCheckResponse(
            success=False,
            error="Failed to parse connectivity check output",
            task_history_id=task_history.id,
        )
