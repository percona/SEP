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

"""Define the ``/api/sep/task-history/`` JSON endpoint merging task history rows.

Expose a server-side merge of ``GET /{task}/history/`` across multiple task
names so the React frontend (``useTaskHistoryByNames``) does not call the Tasks
sub-app directly when rendering plugin task-group execution logs.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.core.db.crud import DEFAULT_PAGINATION_LIMIT, DEFAULT_PAGINATION_OFFSET
from app.core.models import PaginatedResponse
from app.sep.api.task_history_merge import (
    fetch_merged_task_history,
    normalize_task_history_names,
)
from app.sep.deps import TaskAPI
from app.tasks.models import TaskHistoryResponse, TaskHistoryStatusEnum

router = APIRouter()


@router.get("/")
async def list_merged_task_history(
    tasks_api: TaskAPI,
    task_names: Annotated[list[str], Query(min_length=1)],
    task_status: Annotated[TaskHistoryStatusEnum | None, Query(alias="status")] = None,
    offset: int = DEFAULT_PAGINATION_OFFSET,
    limit: int = DEFAULT_PAGINATION_LIMIT,
) -> PaginatedResponse[TaskHistoryResponse]:
    """Return merged execution history for one or more task names.

    Each ``task_names`` value is queried independently against the Tasks API
    with the same ``status`` filter and a widened upstream window starting at
    ``offset=0``; the SEP layer merges, sorts newest-first, then applies the
    client ``offset`` and ``limit`` globally before responding.

    :param tasks_api: The Tasks API client used to fetch upstream history.
    :type tasks_api: TaskAPI
    :param task_names: One or more task names (repeat the query param).
    :type task_names: list[str]
    :param task_status: Optional exact status filter forwarded upstream.
    :type task_status: TaskHistoryStatusEnum | None
    :param offset: Zero-based offset into the merged, sorted result.
    :type offset: int
    :param limit: Page size applied after the global merge sort.
    :type limit: int
    :return: Merged paginated task history across all requested names.
    :rtype: PaginatedResponse[TaskHistoryResponse]
    :raises HTTPException: When every supplied task name is empty after trimming.
    """
    if not normalize_task_history_names(task_names):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="task_names must contain at least one non-empty name",
        )
    return await fetch_merged_task_history(
        tasks_api,
        task_names,
        status=task_status,
        offset=offset,
        limit=limit,
    )
