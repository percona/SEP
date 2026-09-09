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

from app.core.exceptions import HTTPBadGatewayException
from app.core.pagination import (
    DEFAULT_PAGINATION_OFFSET,
    MAX_PAGINATION_LIMIT,
    PaginatedResponse,
    Pagination,
)
from app.core.requests.remote_api import as_json_object, JSONBody, RemoteAPI
from app.sep.api.task_history_actors import SepTaskHistoryResponse
from app.tasks.models import TaskHistoryStatusEnum

__all__ = [
    "fetch_merged_task_history",
    "fetch_task_history_window",
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


def _strict_history_page(payload: JSONBody) -> dict[str, Any]:
    """Return ``payload`` as a usable history page, rejecting any other shape.

    Being a JSON object is not enough, and neither is type-checking whatever the
    keys happen to hold. The walk reads ``items`` with ``extend`` and compares
    ``total`` numerically, so an object *omitting* either key reads as an
    exhausted history exactly as an object carrying a null ``items`` would — the
    "broken upstream looks like a task with no runs" outcome strict mode exists
    to prevent, and the one a lookup with a valid default still lets through.
    Both keys are therefore required as well as well-typed.

    :param payload: The parsed body the Tasks API answered with.
    :return: The payload as a page whose ``items`` and ``total`` are usable.
    :raises HTTPBadGatewayException: If the payload is not a JSON object, or
        omits ``items`` / ``total``, or carries an ``items`` that is not a list
        or a ``total`` that is not a number.
    """
    page = as_json_object(payload)
    if not isinstance(page.get("items"), list):
        raise HTTPBadGatewayException(
            detail="The server answered with a history page with no usable items list."
        )
    if not isinstance(page.get("total"), int):
        raise HTTPBadGatewayException(
            detail="The server answered with a history page with no usable total."
        )
    return page


async def fetch_task_history_window(
    tasks_api: RemoteAPI,
    task_name: str,
    *,
    window_size: int,
    status: TaskHistoryStatusEnum | None = None,
    sort: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Fetch the first ``window_size`` history rows for one task via the Tasks API.

    Issues multiple ``GET /{task}/history/`` requests with ``limit`` capped at
    :data:`~app.core.pagination.MAX_PAGINATION_LIMIT` so large client offsets
    stay within upstream validation.

    :param tasks_api: The Tasks API client.
    :param task_name: Task whose history rows are fetched.
    :param window_size: Number of leading rows required before global merge.
    :param status: Optional exact status filter forwarded upstream.
    :param sort: Optional explicit sort key forwarded upstream. Pass one when
        *which* rows land inside ``window_size`` matters, rather than inheriting
        whatever ordering the Tasks API currently defaults to.
    :param strict: Whether an upstream body that is not a usable history page
        raises instead of reading as an exhausted history. A caller whose result
        answers "has this task ever produced X?" wants this; the merged-history
        endpoint keeps the lenient default because degrading is its established
        contract.
    :return: A paginated-response-shaped dict with accumulated items and
        upstream total.
    :raises HTTPBadGatewayException: Under ``strict``, when the Tasks API answers
        with a body :func:`_strict_history_page` cannot read as a page.
    :raises HTTPException: The error the Tasks API itself answered with, mapped by
        the remote client.
    """
    base_params: dict[str, Any] = {}
    if status is not None:
        base_params["status"] = status.value
    if sort is not None:
        base_params["sort"] = sort

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
        if strict:
            raw = _strict_history_page(raw)
        elif not isinstance(raw, dict):
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
    :func:`_merged_upstream_window_size` and :func:`fetch_task_history_window`),
    then pass the client pagination here so rows are sorted globally and sliced
    ``[offset : offset + limit]``. ``total`` is the sum of upstream totals;
    envelope ``offset`` / ``limit`` echo the client request.

    :param pages: Raw paginated payloads from ``GET /{task}/history/``.
    :param pagination: Validated offset/limit window for the merged page.
    :return: A paginated-response-shaped dict ready for validation.
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
) -> PaginatedResponse[SepTaskHistoryResponse]:
    """Fetch and merge task history for multiple task names via the Tasks API.

    :param tasks_api: The Tasks API client.
    :param task_names: Task names whose history rows should be merged.
    :param status: Optional exact status filter forwarded upstream.
    :param pagination: Validated pagination window for merged results.
    :return: Merged paginated task history, newest-first across all names, with
        actor identifiers left as stored for the caller to resolve.
    """
    unique_names = normalize_task_history_names(task_names)
    window_size = _merged_upstream_window_size(pagination)
    pages = await asyncio.gather(
        *(
            fetch_task_history_window(
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
        [SepTaskHistoryResponse.model_validate(item) for item in merged["items"]],
        merged["total"],
        pagination,
    )
