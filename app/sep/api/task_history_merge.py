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

"""Merge paginated task-history payloads from multiple task names."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.core.pagination import (
    DEFAULT_PAGINATION_OFFSET,
    PaginatedResponse,
    Pagination,
)
from app.core.requests.remote_api import RemoteAPI
from app.tasks.models import TaskHistoryResponse, TaskHistoryStatusEnum

__all__ = [
    "fetch_merged_task_history",
    "merge_task_history_pages",
    "normalize_task_history_names",
]


def normalize_task_history_names(task_names: list[str]) -> list[str]:
    """Return deduplicated task names in stable sorted order.

    :param task_names: Raw task names from the request query string.
    :type task_names: list[str]
    :return: Non-empty unique names sorted lexicographically.
    :rtype: list[str]
    """
    return sorted({name.strip() for name in task_names if name.strip()})


def _history_sort_key(entry: dict[str, Any]) -> float | int:
    """Return a descending sort key for one task-history row."""
    timestamp = entry.get("started_at") or entry.get("created_at")
    if not timestamp:
        return entry.get("id") or 0
    if not isinstance(timestamp, str):
        return entry.get("id") or 0
    try:
        normalized = timestamp.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return entry.get("id") or 0


def _upstream_history_fetch_limit(pagination: Pagination) -> int:
    """Return per-task upstream ``limit`` for a merged page window."""
    return pagination.offset + pagination.limit


def merge_task_history_pages(
    pages: list[dict[str, Any]],
    *,
    pagination: Pagination,
) -> dict[str, Any]:
    """Merge upstream paginated history responses newest-first.

    Upstream callers should fetch each task from ``offset=0`` with a window
    large enough to cover the merged page (see
    :func:`_upstream_history_fetch_limit`), then pass the client pagination
    here so rows are sorted globally and sliced via
    :meth:`Pagination.slice`. ``total`` is the sum of upstream totals;
    envelope ``offset`` / ``limit`` echo the client request.

    :param pages: Raw paginated payloads from ``GET /{task}/history/``.
    :type pages: list[dict[str, Any]]
    :param pagination: Validated offset/limit window for the merged page.
    :type pagination: Pagination
    :return: A paginated-response-shaped dict ready for validation.
    :rtype: dict[str, Any]
    """
    items = sorted(
        (item for page in pages for item in page.get("items", [])),
        key=_history_sort_key,
        reverse=True,
    )
    total = sum(page.get("total", 0) for page in pages)
    return {
        "items": pagination.slice(items),
        "total": total,
        "offset": pagination.offset,
        "limit": pagination.limit,
    }


async def fetch_merged_task_history(
    tasks_api: RemoteAPI,
    task_names: list[str],
    *,
    pagination: Pagination,
    status: TaskHistoryStatusEnum | None = None,
) -> PaginatedResponse[TaskHistoryResponse]:
    """Fetch and merge task history for multiple task names via the Tasks API.

    :param tasks_api: The Tasks API client.
    :type tasks_api: RemoteAPI
    :param task_names: Task names whose history rows should be merged.
    :type task_names: list[str]
    :param status: Optional exact status filter forwarded upstream.
    :type status: TaskHistoryStatusEnum | None
    :param pagination: Validated pagination window for merged results.
    :type pagination: Pagination
    :return: Merged paginated task history, newest-first across all names.
    :rtype: PaginatedResponse[TaskHistoryResponse]
    """
    unique_names = normalize_task_history_names(task_names)
    params: dict[str, Any] = {
        "offset": DEFAULT_PAGINATION_OFFSET,
        "limit": _upstream_history_fetch_limit(pagination),
    }
    if status is not None:
        params["status"] = status.value
    pages = await asyncio.gather(
        *(tasks_api.get(f"/{name}/history/", params=params) for name in unique_names)
    )
    merged = merge_task_history_pages(pages, pagination=pagination)
    return PaginatedResponse.from_pagination(
        [TaskHistoryResponse.model_validate(item) for item in merged["items"]],
        merged["total"],
        pagination,
    )
