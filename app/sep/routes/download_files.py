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

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import status as http_status
from starlette.responses import StreamingResponse
from starlette.types import Send

from app.core.requests import as_json_object
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


class ErrorPrimingStreamingResponse(StreamingResponse):
    """StreamingResponse that checks for upstream errors before sending status.

    Standard StreamingResponse sends HTTP 200 before iterating the body. This
    subclass primes the generator first: if the first pull raises HTTPException,
    it sends that error status instead of 200. This ensures upstream rejections
    (401/403/410/500) propagate correctly rather than appearing as 200 with an
    empty body. See SEP-1878.
    """

    async def stream_response(self, send: Send) -> None:
        """Override to prime the body iterator before sending the start message."""
        body_iter: AsyncIterator[Any] = aiter(self.body_iterator)

        # Prime the generator to surface upstream errors before committing status
        try:
            first_chunk = await anext(body_iter)
        except HTTPException as exc:
            # Upstream rejected — send error response instead of 200
            await send(
                {
                    "type": "http.response.start",
                    "status": exc.status_code,
                    "headers": [
                        (b"content-type", b"application/json"),
                        *[
                            (k.encode(), v.encode())
                            for k, v in (exc.headers or {}).items()
                        ],
                    ],
                }
            )
            detail = exc.detail or "An error occurred"
            await send(
                {
                    "type": "http.response.body",
                    "body": json.dumps({"detail": detail}).encode(),
                    "more_body": False,
                }
            )
            return
        except StopAsyncIteration:
            # Empty file — send normal 200 with empty body
            first_chunk = None

        # Success path — send 200 and stream body
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )

        if first_chunk is not None:
            await send(
                {
                    "type": "http.response.body",
                    "body": self.render(first_chunk),
                    "more_body": True,
                }
            )

        async for chunk in body_iter:
            await send(
                {
                    "type": "http.response.body",
                    "body": self.render(chunk),
                    "more_body": True,
                }
            )

        await send({"type": "http.response.body", "body": b"", "more_body": False})


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
        listing = await tasks_api.get(f"/history/{task_history.id}/files/")
        return {
            name: FileMetadata.model_validate(metadata)
            for name, metadata in (
                as_json_object(listing) if listing is not None else {}
            ).items()
        }
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
    """Stream a task history's archived file as a binary download.

    Uses ErrorPrimingStreamingResponse so that upstream errors (401/403/410/500)
    surface as the real status code rather than a misleading 200 with an empty
    body. See SEP-1878.
    """
    headers = dict(STREAMING_PROXY_HEADERS)
    path = request.query_params.get("path")
    with tasks_client.auth(user.access_token) as tasks_api:
        if path:
            filename = Path(path.rstrip("/")).name or path
            is_dir = False
            try:
                files = as_json_object(
                    await tasks_api.get(f"/history/{task_history.id}/files/")
                )
                meta = files.get(path) or files.get(path.rstrip("/"))
                if isinstance(meta, dict):
                    is_dir = bool(meta.get("is_dir") or meta.get("isDir"))
            except HTTPException:
                logger.debug(
                    "Could not resolve file metadata for %s", path, exc_info=True
                )
            attachment = f"{filename}.tar.gz" if is_dir else filename
            headers["Content-Disposition"] = f'attachment; filename="{attachment}"'

    return ErrorPrimingStreamingResponse(
        task_history_file_stream(
            tasks_client, task_history.id, request, user.access_token
        ),
        media_type="application/octet-stream",
        headers=headers,
    )


async def task_history_file_stream(
    tasks_client: TasksClient,
    task_history_id: int,
    request: Request,
    access_token: str,
) -> AsyncGenerator[bytes, None]:
    """Stream a task history's archived file content as raw bytes.

    Yields the file payload chunk-by-chunk from ``/history/{id}/file/`` without
    any line buffering, so binary, gzip, and tar payloads pass through intact.

    The payload request is authenticated as the user named by ``access_token``,
    under a context this body enters itself rather than inheriting from the
    route.

    :param tasks_client: The Tasks API client to use for streaming the file.
    :param task_history_id: The ID of the task history whose file is to be streamed.
    :param request: The incoming HTTP request.
    :param access_token: Bearer token authenticating the download as the viewing
        user.
    :return: Raw byte chunks of the file payload (binary-safe).
    """
    with tasks_client.auth(access_token) as tasks_api:
        async for chunk in tasks_api.stream_chunks(
            f"/history/{task_history_id}/file/",
            params=request.query_params,
        ):
            yield chunk
