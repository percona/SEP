# Copyright (C) 2025 Percona LLC
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

"""Define routes for listing and downloading files from tasks."""

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.responses import StreamingResponse

from app.sep.deps import (
    CurrentUser,
    get_task_history,
    IsAuthenticated,
    TaskAPI,
    TasksClient,
)
from app.sep.utils.decorators import csrf_exempt
from app.tasks.models import TaskHistoryResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{task_history_id}", dependencies=[IsAuthenticated])
@csrf_exempt
async def list_task_history_files(
    request: Request,  # noqa: ARG001
    task_history: Annotated[TaskHistoryResponse, Depends(get_task_history)],
    tasks_api: TaskAPI,
) -> dict[str, int]:
    """Stream a task history's logs as server-sent events."""
    return await tasks_api.get(f"/history/{task_history.id}/files/")


@router.get("/{task_history_id}/download", dependencies=[IsAuthenticated])
@csrf_exempt
async def download_task_history_file(
    request: Request,
    user: CurrentUser,
    task_history: Annotated[TaskHistoryResponse, Depends(get_task_history)],
    tasks_client: TasksClient,
) -> StreamingResponse:
    """Stream a task history's logs as server-sent events."""
    return StreamingResponse(
        task_history_file_stream(
            tasks_client, task_history.id, request, user.access_token
        ),
        media_type="application/octet-stream",
    )


async def task_history_file_stream(
    tasks_client: TasksClient, task_history_id: int, request: Request, access_token: str
) -> AsyncGenerator[bytes, None]:
    """Stream a task history's logs as server-sent events.

    :param tasks_client: The Tasks API client to use for streaming logs.
    :type tasks_client: TasksClient
    :param task_history_id: The ID of the task history whose logs are to be streamed
    :type task_history_id: int
    :param request: The incoming HTTP request.
    :type request: Request
    :param access_token: The access token for authenticating with the Tasks API.
    :type access_token: str
    :yield: Chunks of log data as bytes.
    :rtype: AsyncGenerator[bytes, None]
    """
    with tasks_client.auth(access_token) as tasks_api:
        async for chunk in tasks_api.stream(
            f"/history/{task_history_id}/file/",
            params=request.query_params,
        ):
            yield chunk
