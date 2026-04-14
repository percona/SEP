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
from pathlib import Path

from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.celery import dispatch_queue_item, get_executor_for_task
from app.tasks.connectivity.models import (
    ConnectivityCheckResponse,
    ConnectivityCheckWrite,
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
            task_history_id=queue_item.id,
        )

    queue_item = await executor.sync_task_history(queue_item)
    await TaskHistoryManager.save(
        session, queue_item, flag_modified_fields=["execution_request"]
    )
    return _parse_check_result(queue_item)


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
