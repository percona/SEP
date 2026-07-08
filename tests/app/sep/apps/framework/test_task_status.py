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

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.core.requests import RemoteAPI
from app.sep.apps.framework import (
    batch_get_latest_statuses,
    extract_latest_history,
    extract_latest_task_status,
    get_task_latest_history,
    get_task_latest_status,
)
from app.tasks.models import (
    LATEST_HISTORY_STATUS_NAMES_MAX,
    TaskHistoryLatestStatus,
    TaskHistoryStatusEnum,
)


def _wire(status: str | None, finished_at: str | None = None) -> dict:
    """Build a ``/history/latest`` wire value for one task name."""
    return {"status": status, "finished_at": finished_at}


def _all_success(json: dict) -> dict:
    """Build a batch response mapping every requested name to a SUCCESS wire value."""
    return {name: _wire("success") for name in json["names"]}


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
    async def test_maps_response_values_to_projection(self) -> None:
        """Map the ``{name: {status, finished_at}}`` response to projections."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post = AsyncMock(
            return_value={
                "a": _wire("success", "2026-07-07T00:00:00"),
                "b": None,
            }
        )

        result = await batch_get_latest_statuses(tasks_api, ["a", "b"])

        assert result == {
            "a": TaskHistoryLatestStatus(
                status=TaskHistoryStatusEnum.SUCCESS,
                finished_at=datetime.fromisoformat("2026-07-07T00:00:00"),
            ),
            "b": None,
        }
        tasks_api.post.assert_awaited_once_with(
            "/history/latest", json={"names": ["a", "b"]}
        )

    @pytest.mark.asyncio
    async def test_accepts_legacy_status_string_shape(self) -> None:
        """Coerce a bare status string (legacy wire shape) into a projection.

        Guards against a rolling upgrade where the endpoint still returns the
        status-only ``{name: status}`` map: the status resolves and
        ``finished_at`` is ``None``.
        """
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post = AsyncMock(return_value={"a": "success", "b": None})

        result = await batch_get_latest_statuses(tasks_api, ["a", "b"])

        assert result == {
            "a": TaskHistoryLatestStatus(
                status=TaskHistoryStatusEnum.SUCCESS, finished_at=None
            ),
            "b": None,
        }

    @pytest.mark.asyncio
    async def test_running_rerun_carries_prior_finish(self) -> None:
        """A RUNNING projection still carries the prior run's ``finished_at``."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post = AsyncMock(
            return_value={"a": _wire("running", "2026-07-06T12:00:00")}
        )

        result = await batch_get_latest_statuses(tasks_api, ["a"])

        assert result["a"].status == TaskHistoryStatusEnum.RUNNING
        assert result["a"].finished_at == datetime.fromisoformat("2026-07-06T12:00:00")

    @pytest.mark.asyncio
    async def test_exactly_max_names_is_one_batch(self) -> None:
        """Send ``LATEST_HISTORY_STATUS_NAMES_MAX`` names in a single POST."""
        names = [f"task-{i}" for i in range(LATEST_HISTORY_STATUS_NAMES_MAX)]
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post = AsyncMock(side_effect=lambda _path, json: _all_success(json))

        result = await batch_get_latest_statuses(tasks_api, names)

        assert tasks_api.post.await_count == 1
        assert len(result) == LATEST_HISTORY_STATUS_NAMES_MAX
        assert all(
            latest.status == TaskHistoryStatusEnum.SUCCESS for latest in result.values()
        )

    @pytest.mark.asyncio
    async def test_over_max_names_chunks_into_multiple_batches(self) -> None:
        """Chunk names beyond the max into multiple POSTs, merging the results."""
        names = [f"task-{i}" for i in range(LATEST_HISTORY_STATUS_NAMES_MAX + 1)]
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.post = AsyncMock(side_effect=lambda _path, json: _all_success(json))

        result = await batch_get_latest_statuses(tasks_api, names)

        expected_batches = len(range(0, len(names), LATEST_HISTORY_STATUS_NAMES_MAX))
        assert tasks_api.post.await_count == expected_batches
        assert set(result) == set(names)
        assert all(
            latest.status == TaskHistoryStatusEnum.SUCCESS for latest in result.values()
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
                {
                    name: _wire("success")
                    for name in names[:LATEST_HISTORY_STATUS_NAMES_MAX]
                },
                RuntimeError("boom"),
            ]
        )

        result = await batch_get_latest_statuses(tasks_api, names)

        expected_batches = len(range(0, len(names), LATEST_HISTORY_STATUS_NAMES_MAX))
        assert tasks_api.post.await_count == expected_batches
        assert all(
            result[name].status == TaskHistoryStatusEnum.SUCCESS
            for name in names[:LATEST_HISTORY_STATUS_NAMES_MAX]
        )
        assert result[names[-1]] is None


class TestExtractLatestHistory:
    """Test suite for ``extract_latest_history``."""

    def test_empty_iterable_yields_all_none(self) -> None:
        """Return a projection with both fields ``None`` for an empty payload."""
        result = extract_latest_history([])
        assert result == TaskHistoryLatestStatus(status=None, finished_at=None)

    def test_combines_newest_status_and_max_finished_at(self) -> None:
        """Return the newest status and the max ``finished_at`` across rows.

        Newest-first payload: an in-progress RUNNING row (no finish) precedes a
        FAILED then a SUCCESS with earlier finish. Status is RUNNING; finish is
        the FAILED (later) time.
        """
        result = extract_latest_history(
            [
                {"status": "running", "finished_at": None},
                {"status": "failed", "finished_at": "2026-07-07T10:00:00"},
                {"status": "success", "finished_at": "2026-07-07T09:00:00"},
            ]
        )

        assert result.status == TaskHistoryStatusEnum.RUNNING
        assert result.finished_at == datetime.fromisoformat("2026-07-07T10:00:00")

    def test_all_unfinished_yields_none_finish(self) -> None:
        """Return ``finished_at=None`` when no row has ever finished."""
        result = extract_latest_history([{"status": "running", "finished_at": None}])
        assert result.status == TaskHistoryStatusEnum.RUNNING
        assert result.finished_at is None

    def test_ignores_finish_from_statusless_row(self) -> None:
        """Exclude ``finished_at`` from rows with a null status.

        Mirrors the tasks-side query (``status IS NOT NULL``): a statusless row
        carrying a ``finished_at`` must not contribute to the max, so the result
        reflects only the status-bearing SUCCESS run.
        """
        result = extract_latest_history(
            [
                {"status": "success", "finished_at": "2026-07-07T09:00:00"},
                {"status": None, "finished_at": "2026-07-07T12:00:00"},
            ]
        )

        assert result.status == TaskHistoryStatusEnum.SUCCESS
        assert result.finished_at == datetime.fromisoformat("2026-07-07T09:00:00")


class TestGetTaskLatestHistory:
    """Test suite for ``get_task_latest_history``."""

    @pytest.mark.asyncio
    async def test_issues_single_history_get(self) -> None:
        """Issue one ``GET /{name}/history/`` and return the latest projection."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.get = AsyncMock(
            return_value={
                "items": [
                    {"status": "running", "finished_at": None},
                    {"status": "success", "finished_at": "2026-07-07T09:00:00"},
                ]
            }
        )

        result = await get_task_latest_history(tasks_api, "task-1")

        assert result.status == TaskHistoryStatusEnum.RUNNING
        assert result.finished_at == datetime.fromisoformat("2026-07-07T09:00:00")
        tasks_api.get.assert_awaited_once_with("/task-1/history/", params=None)

    @pytest.mark.asyncio
    async def test_empty_items_yields_all_none(self) -> None:
        """Return both fields ``None`` when the history payload has no items."""
        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.get = AsyncMock(return_value={"items": []})

        result = await get_task_latest_history(tasks_api, "task-1")

        assert result == TaskHistoryLatestStatus(status=None, finished_at=None)
