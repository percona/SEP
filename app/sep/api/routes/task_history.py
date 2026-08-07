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

"""Define the ``/api/sep/task-history/`` JSON endpoints proxying task history.

Expose task-history reads through the SEP gateway so the React frontend never
calls the Tasks sub-app directly. ``GET /`` either lists all history
(passthrough) or merges ``GET /{task}/history/`` across the supplied task names;
``POST /{id}/stop/`` proxies a stop request for a single history row.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.exceptions import HTTPUnprocessableEntityException
from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.core.utils.fields import ArbitraryMapping
from app.sep.api.openapi import UPSTREAM_TASKS_502_RESPONSE
from app.sep.api.proxy import reraise_upstream_tasks_errors
from app.sep.api.task_history_merge import (
    fetch_merged_task_history,
    normalize_task_history_names,
)
from app.sep.deps import RequireBearerForUnsafeMethods, TaskAPI
from app.tasks.models import TaskHistoryResponse, TaskHistoryStatusEnum

router = APIRouter()


@router.get("/", responses=UPSTREAM_TASKS_502_RESPONSE)
async def list_merged_task_history(
    tasks_api: TaskAPI,
    pagination: PaginationDep,
    *,
    task_names: Annotated[list[str] | None, Query()] = None,
    task_status: Annotated[TaskHistoryStatusEnum | None, Query(alias="status")] = None,
    exclude_internal: Annotated[bool, Query()] = False,
) -> PaginatedResponse[TaskHistoryResponse]:
    """Return task-history rows, listing all of them or merging selected names.

    Three-way on ``task_names``:

    * **omitted** (``None``) -- proxy the upstream ``GET /history/`` list, already
      paginated, forwarding the ``status`` filter, ``exclude_internal`` flag, and
      client ``offset`` / ``limit``.
    * **provided, at least one non-blank name** -- query each name independently
      against the Tasks API, then merge, sort newest-first, and paginate globally.
    * **provided, every name blank after trimming** -- reject with ``422``.

    :param tasks_api: The Tasks API client used to fetch upstream history.
    :param pagination: Validated offset/limit query parameters.
    :param task_names: Zero or more task names (repeat the query param); omit to
        list all history.
    :param task_status: Optional exact status filter forwarded upstream.
    :param exclude_internal: When ``True``, forward the filter to the upstream
        list-all path so internal maintenance tasks are excluded before pagination.
        Not forwarded on the ``task_names`` merge path. Defaults to ``False``.
    :return: Paginated task history, either the upstream list or the merged set.
    :raises HTTPUnprocessableEntityException: When ``task_names`` is supplied but
        every value is empty after trimming.
    :raises HTTPBadGatewayException: For an upstream server error (status >= 500)
        or a connection-level ``OSError``, on either the list-all passthrough or
        the merged-history fan-out.
    """
    if task_names is None:
        params = {
            "offset": pagination.offset,
            "limit": pagination.limit,
            **({"status": task_status.value} if task_status is not None else {}),
            **({"exclude_internal": "true"} if exclude_internal else {}),
        }
        with reraise_upstream_tasks_errors():
            payload = await tasks_api.get("/history/", params=params)
        return PaginatedResponse[TaskHistoryResponse].model_validate(payload)
    if not normalize_task_history_names(task_names):
        raise HTTPUnprocessableEntityException(
            "task_names must contain at least one non-empty name"
        )
    with reraise_upstream_tasks_errors():
        return await fetch_merged_task_history(
            tasks_api,
            task_names,
            status=task_status,
            pagination=pagination,
        )


@router.post(
    "/{task_history_id}/stop/",
    dependencies=[RequireBearerForUnsafeMethods],
    responses=UPSTREAM_TASKS_502_RESPONSE,
)
async def stop_task_history(
    task_history_id: int, tasks_api: TaskAPI
) -> ArbitraryMapping:
    """Dispatch a stop request for a single task-history row to the Tasks API.

    :param task_history_id: The id of the task-history row to stop.
    :param tasks_api: The Tasks API client used to issue the stop request.
    :return: The stopped task-history row as returned by the Tasks API.
    :raises HTTPException: Re-raised unchanged for an upstream client error
        (status < 500), e.g. a ``400`` when the task is not running.
    :raises HTTPBadGatewayException: For an upstream server error (status >= 500)
        or a connection-level ``OSError``.
    """
    with reraise_upstream_tasks_errors():
        return await tasks_api.post(f"/history/{task_history_id}/stop/")
