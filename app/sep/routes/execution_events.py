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

"""Proxy execution events from the Tasks API for SEP (browser) consumers."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import TypeAdapter

from app.sep.deps import (
    get_task_history,
    IsAuthenticated,
    TaskAPI,
)
from app.sep.utils.decorators import csrf_exempt
from app.tasks.models import ExecutionEvent, TaskHistoryResponse

router = APIRouter(tags=["tasks"])


@router.get(
    "/{task_history_id}",
    dependencies=[IsAuthenticated],
)
@csrf_exempt
async def list_task_execution_events(
    request: Request,  # noqa: ARG001
    task_history: Annotated[TaskHistoryResponse, Depends(get_task_history)],
    tasks_api: TaskAPI,
) -> list[ExecutionEvent]:
    """Return executor tracking events for a task history (Tasks API proxy)."""
    raw = await tasks_api.get(f"/history/{task_history.id}/events")
    if raw is None:
        return []
    return TypeAdapter(list[ExecutionEvent]).validate_python(raw)
