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

"""Define tests for the app.sep.connectivity module."""

from unittest.mock import AsyncMock

import pytest

from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import (
    _fetch_connectivity_result,
    _LATEST_RESULTS,
    _record_latest_result,
    annotate_tasks_with_connectivity,
)


@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear the alru_cache and the latest-results snapshot between tests."""
    _fetch_connectivity_result.cache_clear()
    _LATEST_RESULTS.clear()
    yield
    _fetch_connectivity_result.cache_clear()
    _LATEST_RESULTS.clear()


@pytest.fixture
def mock_tasks_api():
    """Return a mock Tasks API client."""
    return AsyncMock(spec=RemoteAPI)


class TestFetchConnectivityResult:
    """Test the cached _fetch_connectivity_result helper."""

    @pytest.mark.asyncio
    async def test_caches_success(self, mock_tasks_api):
        """Return the cached success result on a second call."""
        mock_tasks_api.post.return_value = {"success": True, "error": None}

        first = await _fetch_connectivity_result(
            mock_tasks_api, "node1", "10.0.0.1", 3306, "mysql"
        )
        second = await _fetch_connectivity_result(
            mock_tasks_api, "node1", "10.0.0.1", 3306, "mysql"
        )

        assert first == (True, None, None)
        assert second == (True, None, None)
        mock_tasks_api.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_caches_failure(self, mock_tasks_api):
        """Return the cached failure result on a second call."""
        mock_tasks_api.post.return_value = {
            "success": False,
            "error": "connection refused",
            "task_history_id": 42,
        }

        first = await _fetch_connectivity_result(
            mock_tasks_api, "node1", "10.0.0.1", 3306, "mysql"
        )
        second = await _fetch_connectivity_result(
            mock_tasks_api, "node1", "10.0.0.1", 3306, "mysql"
        )

        assert first == (False, "connection refused", 42)
        assert second == (False, "connection refused", 42)
        mock_tasks_api.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_threads_task_history_id_from_response(self, mock_tasks_api):
        """Carry ``task_history_id`` through from the API response."""
        mock_tasks_api.post.return_value = {
            "success": False,
            "error": "Connectivity check timed out after 30s",
            "task_history_id": 123,
        }

        result = await _fetch_connectivity_result(
            mock_tasks_api, "node1", "10.0.0.1", 3306, "mysql"
        )

        assert result == (False, "Connectivity check timed out after 30s", 123)

    @pytest.mark.asyncio
    async def test_task_history_id_is_none_on_transport_error(self, mock_tasks_api):
        """Return ``task_history_id`` of ``None`` when the API is unreachable."""
        mock_tasks_api.post.side_effect = ConnectionError("timeout")

        result = await _fetch_connectivity_result(
            mock_tasks_api, "node1", "10.0.0.1", 3306, "mysql"
        )

        assert result == (False, "Could not reach the Tasks API", None)


class TestAnnotateTasksWithConnectivity:
    """Test annotate_tasks_with_connectivity helper."""

    def test_annotates_tasks_with_recorded_failure(self):
        """Set ``_connectivity_warning`` to ``True`` for tasks with cached failures."""
        _record_latest_result("node1", "mysql", success=False)
        tasks = [
            {
                "name": "task1",
                "data": {
                    "meta": {
                        "target": "node1",
                        "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
                    }
                },
            }
        ]
        annotate_tasks_with_connectivity(tasks)
        assert tasks[0]["_connectivity_warning"] is True

    def test_annotates_tasks_with_recorded_success(self):
        """Set ``_connectivity_warning`` to ``False`` for tasks with cached successes."""
        _record_latest_result("node1", "mysql", success=True)
        tasks = [
            {
                "name": "task1",
                "data": {
                    "meta": {
                        "target": "node1",
                        "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
                    }
                },
            }
        ]
        annotate_tasks_with_connectivity(tasks)
        assert tasks[0]["_connectivity_warning"] is False

    def test_no_annotation_without_meta(self):
        """Skip annotation for tasks without connectivity meta."""
        tasks = [{"name": "task1", "data": {"meta": {"target": "node1"}}}]
        annotate_tasks_with_connectivity(tasks)
        assert "_connectivity_warning" not in tasks[0]

    def test_no_annotation_when_not_recorded(self):
        """Skip annotation when no snapshot entry exists."""
        tasks = [
            {
                "name": "task1",
                "data": {
                    "meta": {
                        "target": "node1",
                        "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
                    }
                },
            }
        ]
        annotate_tasks_with_connectivity(tasks)
        assert "_connectivity_warning" not in tasks[0]

    def test_handles_empty_task_list(self):
        """Handle an empty task list gracefully."""
        tasks = []
        annotate_tasks_with_connectivity(tasks)
        assert tasks == []

    def test_handles_task_info_format(self):
        """Annotate tasks in the ``task_info`` shape the task listings use."""
        _record_latest_result("node1", "mysql", success=False)
        tasks = [
            {
                "name": "task1",
                "_connectivity_target": "node1",
                "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
            }
        ]
        annotate_tasks_with_connectivity(tasks)
        assert tasks[0]["_connectivity_warning"] is True

    def test_no_annotation_for_task_info_without_service_type(self):
        """Skip annotation for task_info dicts lacking service type."""
        tasks = [
            {
                "name": "task1",
                "_connectivity_target": "node1",
            }
        ]
        annotate_tasks_with_connectivity(tasks)
        assert "_connectivity_warning" not in tasks[0]
