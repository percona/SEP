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
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse

from app.sep.deps import (
    CurrentUser,
    get_task_history,
    IsAuthenticated,
    TaskAPI,
    TasksClient,
)
from app.sep.utils.decorators import csrf_exempt
from app.tasks.models import FileMetadata, TaskHistoryResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/{task_history_id}",
    dependencies=[IsAuthenticated],
    response_model=dict[str, FileMetadata],
)
@csrf_exempt
async def list_task_history_files(
    request: Request,  # noqa: ARG001
    task_history: Annotated[TaskHistoryResponse, Depends(get_task_history)],
    tasks_api: TaskAPI,
) -> dict[str, FileMetadata]:
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
    headers: dict[str, str] = {}
    path = request.query_params.get("path")
    with tasks_client.auth(user.access_token) as tasks_api:
        if path:
            filename = Path(path.rstrip("/")).name or path
            is_dir = False
            try:
                files = await tasks_api.get(f"/history/{task_history.id}/files/")
                meta = files.get(path) or files.get(path.rstrip("/"))
                if isinstance(meta, dict):
                    is_dir = bool(meta.get("is_dir") or meta.get("isDir"))
            except HTTPException:
                logger.debug(
                    "Could not resolve file metadata for %s", path, exc_info=True
                )
            attachment = f"{filename}.tar.gz" if is_dir else filename
            headers["Content-Disposition"] = f'attachment; filename="{attachment}"'

        return StreamingResponse(
            task_history_file_stream(tasks_api, task_history.id, request),
            media_type="application/octet-stream",
            headers=headers or None,
        )


async def task_history_file_stream(
    tasks_api: TaskAPI, task_history_id: int, request: Request
) -> AsyncGenerator[bytes, None]:
    """Stream a task history's logs as server-sent events.

    :param tasks_api: The Tasks API client to use for streaming logs.
    :type tasks_api: TaskAPI
    :param task_history_id: The ID of the task history whose logs are to be streamed
    :type task_history_id: int
    :param request: The incoming HTTP request.
    :type request: Request
    :yield: Chunks of log data as bytes.
    :rtype: AsyncGenerator[bytes, None]
    """
    async for chunk in tasks_api.stream(
        f"/history/{task_history_id}/file/",
        params=request.query_params,
    ):
        yield chunk
