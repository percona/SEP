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

"""Tests for merged task-history helpers."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.pagination import (
    DEFAULT_PAGINATION_LIMIT,
    DEFAULT_PAGINATION_OFFSET,
    MAX_PAGINATION_LIMIT,
    Pagination,
)
from app.sep.api.task_history_merge import (
    fetch_merged_task_history,
    merge_task_history_pages,
)
from app.tasks.models import TaskBackendEnum
from tests.app.factories import TaskFactory

TWO_MERGED_HISTORY_ROWS = 2
MERGED_PAGE_TEST_LIMIT = 2
SUMMED_UPSTREAM_TOTAL = 8
PROPAGATED_TEST_OFFSET = 5
PROPAGATED_TEST_LIMIT = 10


class TestMergeTaskHistoryPages:
    """Tests for ``merge_task_history_pages``."""

    def test_merges_items_newest_first(self) -> None:
        """Sort merged rows by started_at descending."""
        pages = [
            {
                "items": [
                    {
                        "id": 1,
                        "started_at": "2026-01-01T10:00:00+00:00",
                        "status": "success",
                    },
                ],
                "total": 1,
                "offset": 0,
                "limit": 50,
            },
            {
                "items": [
                    {
                        "id": 2,
                        "started_at": "2026-01-02T10:00:00+00:00",
                        "status": "success",
                    },
                ],
                "total": 1,
                "offset": 0,
                "limit": 50,
            },
        ]
        merged = merge_task_history_pages(pages, pagination=Pagination())
        assert [item["id"] for item in merged["items"]] == [2, 1]
        assert merged["total"] == TWO_MERGED_HISTORY_ROWS
        assert merged["offset"] == DEFAULT_PAGINATION_OFFSET
        assert merged["limit"] == DEFAULT_PAGINATION_LIMIT

    def test_propagates_requested_offset_and_limit(self) -> None:
        """Echo caller offset/limit on the merged envelope."""
        pages = [
            {
                "items": [{"id": 1}],
                "total": 1,
                "offset": PROPAGATED_TEST_OFFSET,
                "limit": PROPAGATED_TEST_LIMIT,
            },
            {
                "items": [{"id": 2}],
                "total": 1,
                "offset": PROPAGATED_TEST_OFFSET,
                "limit": PROPAGATED_TEST_LIMIT,
            },
        ]
        pagination = Pagination(
            offset=PROPAGATED_TEST_OFFSET,
            limit=PROPAGATED_TEST_LIMIT,
        )
        merged = merge_task_history_pages(pages, pagination=pagination)
        assert merged["offset"] == PROPAGATED_TEST_OFFSET
        assert merged["limit"] == PROPAGATED_TEST_LIMIT

    def test_caps_merged_items_to_limit(self) -> None:
        """Return at most ``limit`` rows after merging upstream pages."""
        pages = [
            {
                "items": [
                    {"id": 1, "started_at": "2026-01-01T10:00:00+00:00"},
                    {"id": 2, "started_at": "2026-01-03T10:00:00+00:00"},
                ],
                "total": TWO_MERGED_HISTORY_ROWS,
                "offset": 0,
                "limit": MERGED_PAGE_TEST_LIMIT,
            },
            {
                "items": [
                    {"id": 3, "started_at": "2026-01-02T10:00:00+00:00"},
                    {"id": 4, "started_at": "2026-01-04T10:00:00+00:00"},
                ],
                "total": TWO_MERGED_HISTORY_ROWS,
                "offset": 0,
                "limit": MERGED_PAGE_TEST_LIMIT,
            },
        ]
        merged = merge_task_history_pages(
            pages,
            pagination=Pagination(limit=MERGED_PAGE_TEST_LIMIT),
        )
        assert [item["id"] for item in merged["items"]] == [4, 2]
        assert len(merged["items"]) == MERGED_PAGE_TEST_LIMIT

    def test_applies_global_offset_after_sort(self) -> None:
        """Slice the merged sort window with the client offset."""
        pages = [
            {
                "items": [
                    {"id": 1, "started_at": "2026-01-01T10:00:00+00:00"},
                    {"id": 2, "started_at": "2026-01-03T10:00:00+00:00"},
                ],
                "total": 30,
                "offset": 0,
                "limit": 60,
            },
            {
                "items": [
                    {"id": 3, "started_at": "2026-01-02T10:00:00+00:00"},
                    {"id": 4, "started_at": "2026-01-04T10:00:00+00:00"},
                ],
                "total": 30,
                "offset": 0,
                "limit": 60,
            },
        ]
        merged = merge_task_history_pages(
            pages,
            pagination=Pagination(offset=2, limit=2),
        )
        assert [item["id"] for item in merged["items"]] == [3, 1]

    def test_sums_upstream_totals(self) -> None:
        """Expose the sum of upstream totals on the merged envelope."""
        pages = [
            {"items": [], "total": 3, "offset": 0, "limit": 50},
            {"items": [], "total": 5, "offset": 0, "limit": 50},
        ]
        merged = merge_task_history_pages(pages, pagination=Pagination())
        assert merged["total"] == SUMMED_UPSTREAM_TOTAL


LARGE_MERGED_OFFSET = 151
LARGE_MERGED_LIMIT = 50
LARGE_MERGED_WINDOW = LARGE_MERGED_OFFSET + LARGE_MERGED_LIMIT
FIRST_UPSTREAM_PAGE_SIZE = 200
SECOND_UPSTREAM_PAGE_SIZE = 1
TWO_TASK_NAMES = 2
UPSTREAM_PAGES_PER_TASK = 2
MOCK_TASK_HISTORY_TOTAL = 500
MERGED_UPSTREAM_TOTAL = TWO_TASK_NAMES * MOCK_TASK_HISTORY_TOTAL


class TestFetchMergedTaskHistory:
    """Tests for ``fetch_merged_task_history`` upstream paging."""

    @pytest.mark.asyncio
    async def test_pages_upstream_when_window_exceeds_max_limit(self) -> None:
        """Page each task with bounded limits when offset + limit > 200."""
        pagination = Pagination(
            offset=LARGE_MERGED_OFFSET,
            limit=LARGE_MERGED_LIMIT,
        )

        def _history_row(item_id: int, *, task_name: str) -> dict[str, Any]:
            task = TaskFactory.build(
                id=item_id,
                name=task_name,
                owner="BACKUP_MONGO",
                backend=TaskBackendEnum.PROXY,
            )
            task_payload = task.model_dump(mode="json")
            task_payload["data"] = {
                "task": "run-python",
                "meta": {"target": "host1"},
                "payload": "file:///plugins/backup_mongo/pbm_config_payload",
            }
            return {
                "id": item_id,
                "started_at": f"2026-01-{(item_id % 28) + 1:02d}T10:00:00+00:00",
                "status": "success",
                "execution_request": {"task": task_name, "target": "host1"},
                "task": {**task_payload, "deleted_at": None},
            }

        async def mock_get(
            url: str,
            *,
            params: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any]:
            assert params is not None
            assert params["limit"] <= MAX_PAGINATION_LIMIT
            offset = params["offset"]
            limit = params["limit"]
            task_name = url.removesuffix("/history/").removeprefix("/")
            if offset == 0:
                return {
                    "items": [
                        _history_row(item_id, task_name=task_name)
                        for item_id in range(limit)
                    ],
                    "total": MOCK_TASK_HISTORY_TOTAL,
                    "offset": 0,
                    "limit": limit,
                }
            return {
                "items": [
                    _history_row(offset + index, task_name=task_name)
                    for index in range(limit)
                ],
                "total": MOCK_TASK_HISTORY_TOTAL,
                "offset": offset,
                "limit": limit,
            }

        tasks_api = AsyncMock()
        tasks_api.get = AsyncMock(side_effect=mock_get)

        result = await fetch_merged_task_history(
            tasks_api,
            ["task-a", "task-b"],
            pagination=pagination,
        )

        assert tasks_api.get.await_count == TWO_TASK_NAMES * UPSTREAM_PAGES_PER_TASK
        first_page_calls = [
            call.kwargs["params"]
            for call in tasks_api.get.await_args_list
            if call.kwargs["params"]["offset"] == DEFAULT_PAGINATION_OFFSET
        ]
        second_page_calls = [
            call.kwargs["params"]
            for call in tasks_api.get.await_args_list
            if call.kwargs["params"]["offset"] == FIRST_UPSTREAM_PAGE_SIZE
        ]
        assert len(first_page_calls) == TWO_TASK_NAMES
        assert all(
            params["limit"] == FIRST_UPSTREAM_PAGE_SIZE for params in first_page_calls
        )
        assert len(second_page_calls) == TWO_TASK_NAMES
        assert all(
            params["limit"] == SECOND_UPSTREAM_PAGE_SIZE for params in second_page_calls
        )
        assert len(result.items) == LARGE_MERGED_LIMIT
        assert result.offset == LARGE_MERGED_OFFSET
        assert result.limit == LARGE_MERGED_LIMIT
        assert result.total == MERGED_UPSTREAM_TOTAL
