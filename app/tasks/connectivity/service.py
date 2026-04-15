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
import contextvars
import json
from collections.abc import AsyncGenerator
from pathlib import Path

from async_lru import alru_cache
from sqlalchemy.orm import undefer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.celery import dispatch_queue_item, get_executor_for_task
from app.tasks.connectivity.constants import CONNECTIVITY_CHECK_TIMEOUT
from app.tasks.connectivity.models import (
    ConnectivityCheckResponse,
    ConnectivityCheckWrite,
    ConnectivityServiceType,
    REQUIREMENTS_BY_SERVICE_TYPE,
)
from app.tasks.crud import TaskHistoryManager
from app.tasks.deps import get_executable_task_by_name
from app.tasks.logs.log_reader import iter_task_history_logs
from app.tasks.models import (
    SYSTEM_USER,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLog,
    TaskLogType,
)

PAYLOAD_PATH = Path(__file__).parent / "payload.py"
POLL_INTERVAL = 2
FRESH_FETCH_MAX_ATTEMPTS = 3
FRESH_FETCH_INTERVAL = 0.5
RESULT_CACHE_TTL = 300
RESULT_CACHE_MAXSIZE = 128

_cached_check_session_ctx: contextvars.ContextVar[AsyncSession] = (
    contextvars.ContextVar("_cached_check_session_ctx")
)


@alru_cache(maxsize=RESULT_CACHE_MAXSIZE, ttl=RESULT_CACHE_TTL)
async def _cached_check_connectivity(
    target: str,
    host: str,
    port: int,
    service_type: ConnectivityServiceType,
) -> tuple[bool, str | None]:
    """Run ``check_connectivity`` and cache the (success, error) result.

    The ``AsyncSession`` is NOT part of the cache key — it is resolved at
    call time via :data:`_cached_check_session_ctx`, which the public
    :func:`check_connectivity_with_cache` wrapper sets on each invocation.
    Using ``alru_cache`` keeps the cache consistent with the rest of the
    codebase (see ``app/core/auth/providers/casdoor.py``).

    :param target: The Nomad node name.
    :type target: str
    :param host: The database host address.
    :type host: str
    :param port: The database port.
    :type port: int
    :param service_type: The database service type.
    :type service_type: ConnectivityServiceType
    :return: A tuple of ``(success, error)``.
    :rtype: tuple[bool, str | None]
    """
    session = _cached_check_session_ctx.get()
    request = ConnectivityCheckWrite(
        target=target,
        host=host,
        port=port,
        service_type=service_type,
        timeout=CONNECTIVITY_CHECK_TIMEOUT,
    )
    result = await check_connectivity(session, request)
    return result.success, result.error


async def check_connectivity_with_cache(
    session: AsyncSession,
    *,
    target: str,
    host: str,
    port: int,
    service_type: ConnectivityServiceType,
) -> tuple[bool, str | None]:
    """Run :func:`check_connectivity` with results cached by target+type.

    Results for a given ``(target, host, port, service_type)`` tuple are
    cached for ``RESULT_CACHE_TTL`` seconds via :func:`async_lru.alru_cache`.
    The session is passed through a :class:`~contextvars.ContextVar` so it
    does not participate in the cache key.

    :param session: The async database session.
    :type session: AsyncSession
    :param target: The Nomad node name.
    :type target: str
    :param host: The database host address.
    :type host: str
    :param port: The database port.
    :type port: int
    :param service_type: The database service type.
    :type service_type: ConnectivityServiceType
    :return: A tuple of ``(success, error)``.
    :rtype: tuple[bool, str | None]
    """
    token = _cached_check_session_ctx.set(session)
    try:
        return await _cached_check_connectivity(target, host, port, service_type)
    finally:
        _cached_check_session_ctx.reset(token)


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
    await session.refresh(queue_item, attribute_names=["execution_request"])

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
        await session.refresh(queue_item, attribute_names=["execution_request"])

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
    return await _parse_check_result(session, fresh_queue_item)


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
        if await _has_run_script_logs(session, task_history):
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

    The ``execution_request`` column is declared as a deferred
    ``column_property`` on :class:`TaskHistory`, so the re-fetch must
    explicitly ``undefer`` it — otherwise the attribute is left unloaded
    and any downstream sync-context read (e.g. ``iter_logs`` walking
    ``self.execution_request.tracking``) would fire a lazy SELECT and
    raise ``MissingGreenlet`` against the async driver.

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
    return await TaskHistoryManager.get_or_404(
        session,
        query_options=[undefer(TaskHistory.execution_request)],
        id=task_history_id,
    )


async def _iter_run_script_logs(
    session: AsyncSession,
    task_history: TaskHistory,
) -> AsyncGenerator[TaskLog, None]:
    """Yield ``run-script`` logs from either legacy or chunked storage.

    :param session: The async database session.
    :type session: AsyncSession
    :param task_history: The task history row being inspected.
    :type task_history: TaskHistory
    :yield: Log chunks for the ``run-script`` source.
    :rtype: AsyncGenerator[TaskLog, None]
    """
    iter_logs = getattr(task_history, "iter_logs", None)
    if callable(iter_logs):
        for log in iter_logs(step="run-script"):
            yield log
        return

    async for log in iter_task_history_logs(session, task_history, source="run-script"):
        yield log


async def _has_run_script_logs(session: AsyncSession, task_history: TaskHistory) -> bool:
    """Return whether ``task_history`` has any ``run-script`` step output.

    :param session: The async database session.
    :type session: AsyncSession
    :param task_history: The task history record to inspect.
    :type task_history: TaskHistory
    :return: ``True`` if a non-empty stdout or stderr log exists for the
        ``run-script`` step, ``False`` otherwise.
    :rtype: bool
    """
    async for log in _iter_run_script_logs(session, task_history):
        if log.msg:
            return True
    return False


async def _parse_check_result(
    session: AsyncSession, task_history: TaskHistory
) -> ConnectivityCheckResponse:
    """Extract connectivity result from task logs.

    :param session: The async database session.
    :type session: AsyncSession
    :param task_history: The completed task history record.
    :type task_history: TaskHistory
    :return: The parsed connectivity check result.
    :rtype: ConnectivityCheckResponse
    """
    if task_history.id is None:
        raise RuntimeError("_parse_check_result called with unsaved TaskHistory")

    if task_history.status == TaskHistoryStatusEnum.FAILED:
        stderr = ""
        async for log in _iter_run_script_logs(session, task_history):
            if log.type == TaskLogType.STDERR:
                stderr += log.msg or ""
        return ConnectivityCheckResponse(
            success=False,
            error=stderr or "Task failed",
            task_history_id=task_history.id,
        )

    stdout = ""
    async for log in _iter_run_script_logs(session, task_history):
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
