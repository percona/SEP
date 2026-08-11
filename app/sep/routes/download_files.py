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

"""Define routes for listing and downloading files from tasks."""

import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import status as http_status
from starlette.responses import StreamingResponse

from app.sep.deps import (
    ApiCurrentUser,
    get_task_history,
    IsApiAuthenticated,
    TaskAPI,
    TasksClient,
)
from app.sep.routes import STREAMING_PROXY_HEADERS
from app.tasks.models import FileMetadata, TaskHistoryResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tasks"])


@router.get(
    "/{task_history_id}",
    dependencies=[IsApiAuthenticated],
)
async def list_task_history_files(
    request: Request,  # noqa: ARG001
    task_history: Annotated[TaskHistoryResponse, Depends(get_task_history)],
    tasks_api: TaskAPI,
) -> dict[str, FileMetadata]:
    """Return files available for the given task history."""
    try:
        return await tasks_api.get(f"/history/{task_history.id}/files/") or {}
    except HTTPException as exc:
        if exc.status_code in (
            http_status.HTTP_400_BAD_REQUEST,
            http_status.HTTP_409_CONFLICT,
        ):
            return {}
        raise


@router.get("/{task_history_id}/download", dependencies=[IsApiAuthenticated])
async def download_task_history_file(
    request: Request,
    user: ApiCurrentUser,
    task_history: Annotated[TaskHistoryResponse, Depends(get_task_history)],
    tasks_client: TasksClient,
) -> StreamingResponse:
    """Stream a task history's archived file as a binary download."""
    headers = dict(STREAMING_PROXY_HEADERS)
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
            headers=headers,
        )


async def task_history_file_stream(
    tasks_api: TaskAPI, task_history_id: int, request: Request
) -> AsyncGenerator[bytes, None]:
    """Stream a task history's archived file content as raw bytes.

    Yields the file payload chunk-by-chunk from ``/history/{id}/file/`` without
    any line buffering, so binary, gzip, and tar payloads pass through intact.

    :param tasks_api: The Tasks API client to use for streaming the file.
    :type tasks_api: TaskAPI
    :param task_history_id: The ID of the task history whose file is to be streamed.
    :type task_history_id: int
    :param request: The incoming HTTP request.
    :type request: Request
    :yield: Raw byte chunks of the file payload (binary-safe).
    :rtype: AsyncGenerator[bytes, None]
    """
    async for chunk in tasks_api.stream_chunks(
        f"/history/{task_history_id}/file/",
        params=request.query_params,
    ):
        yield chunk
