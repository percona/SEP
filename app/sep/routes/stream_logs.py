# Copyright 2025 Percona LLC
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
            async for log_entry in tasks_api.stream(
                f"/history/{task_history_id}/logs/", params=request.query_params
            ):
                if log_entry:
                    yield f"data: {log_entry.decode()}\n\n"
            # TODO(yan): Don't wait for task to finish
            # SEP-379
            wait_interval = 5
            task_history = await tasks_api.get(f"/history/{task_history_id}")
            while task_history["status"] == TaskHistoryStatusEnum.RUNNING:
                await asyncio.sleep(wait_interval)
                task_history = await tasks_api.get(f"/history/{task_history_id}")
        yield f"event: finish\ndata: {json.dumps({'status': task_history['status']})}\n\n"
    except HTTPException as exc:
        logger.exception("HTTP error streaming task logs [%s]", exc.status_code)
        payload = {"code": exc.status_code, "detail": exc.detail}
        yield f"event: sep-error\ndata: {json.dumps(payload)}\n\n"
    except Exception as exc:
        logger.exception("Error streaming task logs")
        yield f"event: sep-error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
