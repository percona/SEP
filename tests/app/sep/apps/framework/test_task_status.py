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

"""Tests for the shared task-status framework helpers."""

from unittest.mock import AsyncMock

import pytest

from app.core.requests import RemoteAPI
from app.sep.apps.framework import (
    batch_get_latest_statuses,
    extract_latest_task_status,
    get_task_latest_status,
)
from app.tasks.models import LATEST_HISTORY_STATUS_NAMES_MAX, TaskHistoryStatusEnum


class TestExtractLatestTaskStatus:
    """Test suite for ``extract_latest_task_status``."""

    def test_empty_iterable_returns_none(self) -> None:
        """Return ``None`` when no histories are provided."""
        assert extract_latest_task_status([]) is None

    def test_returns_first_non_none_status(self) -> None:
        """Return the first non-``None`` status encountered."""
        result = extract_latest_task_status([{"status": "success"}])
        assert result == TaskHistoryStatusEnum.SUCCESS

    def test_skips_leading_none_entries(self) -> None:
        """Skip leading entries with ``status=None`` and return the next status."""
        result = extract_latest_task_status([{"status": None}, {"status": "failed"}])
        assert result == TaskHistoryStatusEnum.FAILED

    def test_skips_entries_missing_status_key(self) -> None:
        """Treat a missing ``status`` key as ``None`` and continue."""
        result = extract_latest_task_status([{}, {"status": "running"}])
        assert result == TaskHistoryStatusEnum.RUNNING

    def test_all_none_returns_none(self) -> None:
        """Return ``None`` when every history entry has ``status=None``."""
        assert extract_latest_task_status([{"status": None}, {"status": None}]) is None

    def test_unknown_status_raises_value_error(self) -> None:
        """Raise ``ValueError`` for a status string outside the enum."""
        with pytest.raises(ValueError, match="not-a-real-status"):
            extract_latest_task_status([{"status": "not-a-real-status"}])


class TestGetTaskLatestStatus:
    """Test suite for ``get_task_latest_status``."""

    @pytest.mark.asyncio
    async def test_issues_single_history_get(self) -> None:
        """Issue exactly one ``GET /{name}/history/`` and return the latest status."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.get = AsyncMock(return_value={"items": [{"status": "success"}]})

        result = await get_task_latest_status(tasks_api, "task-1")

        assert result == TaskHistoryStatusEnum.SUCCESS
        tasks_api.get.assert_awaited_once_with("/task-1/history/", params=None)

    @pytest.mark.asyncio
    async def test_passes_params_through_verbatim(self) -> None:
        """Forward the ``params`` kwarg verbatim to the history GET."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.get = AsyncMock(return_value={"items": [{"status": "running"}]})

        result = await get_task_latest_status(
            tasks_api, "task-1", params={"limit": 1, "offset": 0}
        )

        assert result == TaskHistoryStatusEnum.RUNNING
        tasks_api.get.assert_awaited_once_with(
            "/task-1/history/", params={"limit": 1, "offset": 0}
        )

    @pytest.mark.asyncio
    async def test_empty_items_returns_none(self) -> None:
        """Return ``None`` when the history payload has no items."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.get = AsyncMock(return_value={"items": []})

        assert await get_task_latest_status(tasks_api, "task-1") is None


class TestBatchGetLatestStatuses:
    """Test suite for ``batch_get_latest_statuses``."""

    @pytest.mark.asyncio
    async def test_empty_names_returns_empty_without_call(self) -> None:
        """Return ``{}`` without any upstream POST when ``names`` is empty."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post = AsyncMock()

        assert await batch_get_latest_statuses(tasks_api, []) == {}
        tasks_api.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_maps_response_values_to_enum(self) -> None:
        """Map the ``{name: status}`` response to ``{name: enum | None}``."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post = AsyncMock(return_value={"a": "success", "b": None})

        result = await batch_get_latest_statuses(tasks_api, ["a", "b"])

        assert result == {"a": TaskHistoryStatusEnum.SUCCESS, "b": None}
        tasks_api.post.assert_awaited_once_with(
            "/history/latest", json={"names": ["a", "b"]}
        )

    @pytest.mark.asyncio
    async def test_exactly_max_names_is_one_batch(self) -> None:
        """Send ``LATEST_HISTORY_STATUS_NAMES_MAX`` names in a single POST."""
        names = [f"task-{i}" for i in range(LATEST_HISTORY_STATUS_NAMES_MAX)]
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post = AsyncMock(
            side_effect=lambda _path, json: dict.fromkeys(json["names"], "success")
        )

        result = await batch_get_latest_statuses(tasks_api, names)

        assert tasks_api.post.await_count == 1
        assert len(result) == LATEST_HISTORY_STATUS_NAMES_MAX
        assert all(
            status == TaskHistoryStatusEnum.SUCCESS for status in result.values()
        )

    @pytest.mark.asyncio
    async def test_over_max_names_chunks_into_multiple_batches(self) -> None:
        """Chunk names beyond the max into multiple POSTs, merging the results."""
        names = [f"task-{i}" for i in range(LATEST_HISTORY_STATUS_NAMES_MAX + 1)]
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post = AsyncMock(
            side_effect=lambda _path, json: dict.fromkeys(json["names"], "success")
        )

        result = await batch_get_latest_statuses(tasks_api, names)

        expected_batches = len(range(0, len(names), LATEST_HISTORY_STATUS_NAMES_MAX))
        assert tasks_api.post.await_count == expected_batches
        assert set(result) == set(names)
        assert all(
            status == TaskHistoryStatusEnum.SUCCESS for status in result.values()
        )

    @pytest.mark.asyncio
    async def test_upstream_exception_degrades_to_all_none(self) -> None:
        """Seed every name to ``None`` when the upstream POST raises."""
        names = ["a", "b", "c"]
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post = AsyncMock(side_effect=RuntimeError("boom"))

        result = await batch_get_latest_statuses(tasks_api, names)

        assert result == dict.fromkeys(names)

    @pytest.mark.asyncio
    async def test_failed_chunk_isolated_from_succeeding_chunk(self) -> None:
        """Keep a failed chunk seeded-``None`` without affecting other chunks."""
        names = [f"task-{i}" for i in range(LATEST_HISTORY_STATUS_NAMES_MAX + 1)]
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post = AsyncMock(
            side_effect=[
                dict.fromkeys(names[:LATEST_HISTORY_STATUS_NAMES_MAX], "success"),
                RuntimeError("boom"),
            ]
        )

        result = await batch_get_latest_statuses(tasks_api, names)

        expected_batches = len(range(0, len(names), LATEST_HISTORY_STATUS_NAMES_MAX))
        assert tasks_api.post.await_count == expected_batches
        assert all(
            result[name] == TaskHistoryStatusEnum.SUCCESS
            for name in names[:LATEST_HISTORY_STATUS_NAMES_MAX]
        )
        assert result[names[-1]] is None
