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

from app.core.db.crud import DEFAULT_PAGINATION_LIMIT, DEFAULT_PAGINATION_OFFSET
from app.core.models import PaginatedResponse
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


def merge_task_history_pages(
    pages: list[dict[str, Any]],
    *,
    offset: int = DEFAULT_PAGINATION_OFFSET,
    limit: int = DEFAULT_PAGINATION_LIMIT,
) -> dict[str, Any]:
    """Merge upstream paginated history responses newest-first.

    Mirrors the frontend ``mergeTaskHistoryPages`` helper previously used by
    ``useTaskHistoryByNames``: each upstream page is fetched with the same
    ``offset`` / ``limit`` / ``status`` filters, then items are concatenated,
    sorted by ``started_at`` (falling back to ``created_at`` then ``id``), and
    wrapped in a single paginated envelope whose ``total`` is the sum of the
    upstream totals. ``offset`` and ``limit`` on the envelope echo the request
    parameters so consumers can compute the next page.

    :param pages: Raw paginated payloads from ``GET /{task}/history/``.
    :type pages: list[dict[str, Any]]
    :param offset: Zero-based offset forwarded to each upstream history call.
    :type offset: int
    :param limit: Page size forwarded to each upstream history call.
    :type limit: int
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
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


async def fetch_merged_task_history(
    tasks_api: RemoteAPI,
    task_names: list[str],
    *,
    status: TaskHistoryStatusEnum | None = None,
    offset: int = DEFAULT_PAGINATION_OFFSET,
    limit: int = DEFAULT_PAGINATION_LIMIT,
) -> PaginatedResponse[TaskHistoryResponse]:
    """Fetch and merge task history for multiple task names via the Tasks API.

    :param tasks_api: The Tasks API client.
    :type tasks_api: RemoteAPI
    :param task_names: Task names whose history rows should be merged.
    :type task_names: list[str]
    :param status: Optional exact status filter forwarded upstream.
    :type status: TaskHistoryStatusEnum | None
    :param offset: Zero-based offset forwarded to each upstream history call.
    :type offset: int
    :param limit: Page size forwarded to each upstream history call.
    :type limit: int
    :return: Merged paginated task history, newest-first across all names.
    :rtype: PaginatedResponse[TaskHistoryResponse]
    """
    unique_names = normalize_task_history_names(task_names)
    params: dict[str, Any] = {"offset": offset, "limit": limit}
    if status is not None:
        params["status"] = status.value
    pages = await asyncio.gather(
        *(tasks_api.get(f"/{name}/history/", params=params) for name in unique_names)
    )
    merged = merge_task_history_pages(pages, offset=offset, limit=limit)
    return PaginatedResponse[TaskHistoryResponse](
        items=[TaskHistoryResponse.model_validate(item) for item in merged["items"]],
        total=merged["total"],
        offset=merged["offset"],
        limit=merged["limit"],
    )
