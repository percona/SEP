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

"""Define routes for streaming tasks logs."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from aiohttp import ClientTimeout
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse

from app.sep.deps import (
    CurrentUser,
    get_task_history,
    IsAuthenticated,
    TasksClient,
)
from app.sep.utils.decorators import csrf_exempt
from app.tasks.models import TaskHistoryResponse, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{task_history_id}", dependencies=[IsAuthenticated])
@csrf_exempt
async def task_logs_event_stream(
    request: Request,
    user: CurrentUser,
    task_history: Annotated[TaskHistoryResponse, Depends(get_task_history)],
    tasks_client: TasksClient,
) -> StreamingResponse:
    """Stream a task history's logs as server-sent events."""
    logger.debug("request.state.is_csrf_exempt is %s", request.state.is_csrf_exempt)
    return StreamingResponse(
        task_history_logs_event_stream(
            tasks_client, task_history.id, request, user.access_token
        ),
        media_type="text/event-stream",
    )


# TODO(yan): Put stream_task_history_logs in a proper TasksAPI SDK class
# SEP-130
async def task_history_logs_event_stream(
    tasks_client: TasksClient, task_history_id: int, request: Request, access_token: str
) -> AsyncGenerator[str, None]:
    """Stream logs from a task history as server-sent events.

    Streams log lines for a given task history ID from the Tasks API and yields them
    formatted as server-sent events.

    :param tasks_client: The TaskAPI client for interacting with the Tasks service.
    :type tasks_client: RemoteAPI
    :param task_history_id: The ID of the task history whose logs to stream.
    :type task_history_id: int
    :param request: The FastAPI request object, used to access query parameters.
    :type request: Request
    :yield: Log entries formatted as server-sent events.
    :rtype: str
    """
    try:
        with tasks_client.auth(access_token) as tasks_api:
            poll_interval = 2
            # Wait for task to leave PENDING before attempting to stream logs.
            # Calling /logs/ on a PENDING task returns 409, which would short-circuit
            # the generator via the HTTPException handler before event: finish is sent,
            # causing EventSource to fire onerror ("Stream failed.").
            task_history = await tasks_api.get(f"/history/{task_history_id}")
            while task_history["status"] == TaskHistoryStatusEnum.PENDING:
                await asyncio.sleep(poll_interval)
                task_history = await tasks_api.get(f"/history/{task_history_id}")

            # No read timeout: log stream can stall under backpressure (e.g. ~26MB)
            # and must not be killed by the default sock_read=120.
            #
            # Retry the live stream until data arrives or the task reaches a terminal
            # state. On an immediate connect the Nomad allocation exists but TaskStates
            # is still empty, so the first /logs/ call returns with no data. Retrying
            # after a short delay avoids a 30-second DB-polling wait for
            # sync_running_tasks to mark the task terminal.
            received_data = False
            while not received_data:
                async for log_entry in tasks_api.stream(
                    f"/history/{task_history_id}/logs/",
                    params=request.query_params,
                    timeout=ClientTimeout(sock_read=None),
                ):
                    if log_entry:
                        received_data = True
                        yield f"data: {log_entry.decode()}\n\n"
                if received_data:
                    break
                task_history = await tasks_api.get(f"/history/{task_history_id}")
                if task_history["status"] != TaskHistoryStatusEnum.RUNNING:
                    # Task finished before TaskStates was ever populated;
                    # fall through to the stored-logs re-fetch below.
                    break
                await asyncio.sleep(poll_interval)

            # If the live stream never produced data (task finished too fast for the
            # Nomad allocation to expose TaskStates), re-fetch from stored history.
            if not received_data:
                task_history = await tasks_api.get(f"/history/{task_history_id}")
                async for log_entry in tasks_api.stream(
                    f"/history/{task_history_id}/logs/",
                    params=request.query_params,
                    timeout=ClientTimeout(sock_read=None),
                ):
                    if log_entry:
                        yield f"data: {log_entry.decode()}\n\n"
        yield f"event: finish\ndata: {json.dumps({'status': task_history['status']})}\n\n"
    except TimeoutError as exc:
        logger.warning(
            "Timeout while streaming task logs task_history_id=%s: %s",
            task_history_id,
            exc,
        )
        yield f"event: sep-error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
    except asyncio.CancelledError:
        logger.info(
            "Task log stream cancelled task_history_id=%s (e.g. user closed panel or switched tab)",
            task_history_id,
        )
        raise
    except HTTPException as exc:
        logger.exception("HTTP error streaming task logs [%s]", exc.status_code)
        payload = {"code": exc.status_code, "detail": exc.detail}
        yield f"event: sep-error\ndata: {json.dumps(payload)}\n\n"
    except Exception as exc:
        logger.exception(
            "Error streaming task logs task_history_id=%s (non-timeout, non-cancellation)",
            task_history_id,
        )
        yield f"event: sep-error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
