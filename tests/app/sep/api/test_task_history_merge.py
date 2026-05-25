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

from app.sep.api.task_history_merge import merge_task_history_pages

TWO_MERGED_HISTORY_ROWS = 2
SUMMED_UPSTREAM_TOTAL = 8


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
        merged = merge_task_history_pages(pages)
        assert [item["id"] for item in merged["items"]] == [2, 1]
        assert merged["total"] == TWO_MERGED_HISTORY_ROWS
        assert merged["offset"] == 0
        assert merged["limit"] == TWO_MERGED_HISTORY_ROWS

    def test_sums_upstream_totals(self) -> None:
        """Expose the sum of upstream totals on the merged envelope."""
        pages = [
            {"items": [], "total": 3, "offset": 0, "limit": 50},
            {"items": [], "total": 5, "offset": 0, "limit": 50},
        ]
        merged = merge_task_history_pages(pages)
        assert merged["total"] == SUMMED_UPSTREAM_TOTAL
