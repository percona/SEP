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
    MAX_PAGINATION_LIMIT,
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


def _merged_upstream_window_size(pagination: Pagination) -> int:
    """Return per-task upstream fetch size for a merged page window."""
    return pagination.offset + pagination.limit


async def _fetch_task_history_window(
    tasks_api: RemoteAPI,
    task_name: str,
    *,
    window_size: int,
    status: TaskHistoryStatusEnum | None = None,
) -> dict[str, Any]:
    """Fetch the first ``window_size`` history rows for one task via the Tasks API.

    Issues multiple ``GET /{task}/history/`` requests with ``limit`` capped at
    :data:`~app.core.pagination.MAX_PAGINATION_LIMIT` so large client offsets
    stay within upstream validation.

    :param tasks_api: The Tasks API client.
    :type tasks_api: RemoteAPI
    :param task_name: Task whose history rows are fetched.
    :type task_name: str
    :param window_size: Number of leading rows required before global merge.
    :type window_size: int
    :param status: Optional exact status filter forwarded upstream.
    :type status: TaskHistoryStatusEnum | None
    :return: A paginated-response-shaped dict with accumulated items and
        upstream total.
    :rtype: dict[str, Any]
    """
    base_params: dict[str, Any] = {}
    if status is not None:
        base_params["status"] = status.value

    all_items: list[dict[str, Any]] = []
    upstream_offset = 0
    total = 0
    while len(all_items) < window_size:
        page_limit = min(MAX_PAGINATION_LIMIT, window_size - len(all_items))
        raw = await tasks_api.get(
            f"/{task_name}/history/",
            params={
                **base_params,
                "offset": upstream_offset,
                "limit": page_limit,
            },
        )
        if not isinstance(raw, dict):
            raw = {}
        page_items = raw.get("items", [])
        if "total" in raw:
            total = raw["total"]
        if not page_items:
            break
        all_items.extend(page_items)
        upstream_offset += len(page_items)
        if upstream_offset >= total or len(page_items) < page_limit:
            break

    return {
        "items": all_items,
        "total": total,
        "offset": DEFAULT_PAGINATION_OFFSET,
        "limit": window_size,
    }


def merge_task_history_pages(
    pages: list[dict[str, Any]],
    *,
    pagination: Pagination,
) -> dict[str, Any]:
    """Merge upstream paginated history responses newest-first.

    Upstream callers should fetch each task from ``offset=0`` with a window
    large enough to cover the merged page (see
    :func:`_merged_upstream_window_size` and :func:`_fetch_task_history_window`),
    then pass the client pagination here so rows are sorted globally and sliced
    ``[offset : offset + limit]``. ``total`` is the sum of upstream totals;
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
    window_size = _merged_upstream_window_size(pagination)
    pages = await asyncio.gather(
        *(
            _fetch_task_history_window(
                tasks_api,
                name,
                window_size=window_size,
                status=status,
            )
            for name in unique_names
        )
    )
    merged = merge_task_history_pages(pages, pagination=pagination)
    return PaginatedResponse.from_pagination(
        [TaskHistoryResponse.model_validate(item) for item in merged["items"]],
        merged["total"],
        pagination,
    )
