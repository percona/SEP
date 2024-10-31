"""Define routes for streaming tasks logs."""

import json
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from app.sep.deps import get_task_history, IsAuthenticated, TaskAPI
from app.tasks.models import TaskHistoryResponse

router = APIRouter()


@router.get("/{task_history_id}", dependencies=[IsAuthenticated])
async def archives_logs_event_stream(
    task_history: Annotated[TaskHistoryResponse, Depends(get_task_history)],
    tasks_api: TaskAPI,
) -> StreamingResponse:
    """Stream a task history's logs as server-sent events."""
    return StreamingResponse(
        task_history_logs_event_stream(tasks_api, task_history.id),
        media_type="text/event-stream",
    )


# TODO(yan): Put stream_task_history_logs in a proper TasksAPI SDK class
# SEP-130
async def task_history_logs_event_stream(
    tasks_api: TaskAPI, task_history_id: int
) -> AsyncGenerator[str, None]:
    """Stream logs from a task history as server-sent events.

    Streams log lines for a given task history ID from the Tasks API and yields them
    formatted as server-sent events.

    :param tasks_api: The TaskAPI client for interacting with the Tasks service.
    :type tasks_api: RemoteAPI
    :param task_history_id: The ID of the task history whose logs to stream.
    :type task_history_id: int
    :yield: Log entries formatted as server-sent events.
    :rtype: str
    """
    i = 1
    async for log_entry in tasks_api.stream(f"/history/{task_history_id}/logs/"):
        if log_entry:
            log_data = json.loads(log_entry)
            for line in log_data["msg"].splitlines():
                log_data["msg"] = f"{line}\n"
                log_data["id"] = i
                yield f"data: {json.dumps(log_data)}\n\n"
                i += 1
    yield "event: finish\ndata: true\n\n"
