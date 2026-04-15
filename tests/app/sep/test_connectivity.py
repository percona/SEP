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

import time
from collections import OrderedDict
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError
from fastapi import HTTPException, Request, status

from app.core.requests import RemoteAPI
from app.sep.connectivity import (
    _connectivity_cache,
    annotate_tasks_with_connectivity,
    CACHE_TTL,
    check_and_warn_connectivity,
    get_connectivity_status,
    maybe_check_connectivity,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the connectivity cache before and after each test."""
    _connectivity_cache.clear()
    yield
    _connectivity_cache.clear()


@pytest.fixture
def mock_tasks_api():
    """Return a mock Tasks API client."""
    return AsyncMock(spec=RemoteAPI)


@pytest.fixture
def dummy_request():
    """Create a dummy Request with a messages attribute in its state."""
    scope = {
        "type": "http",
        "headers": [],
        "client": ("127.0.0.1", 80),
        "path": "/",
    }
    req = Request(scope)
    req.state.messages = OrderedDict()
    return req


class TestGetConnectivityStatus:
    """Test get_connectivity_status cache lookups."""

    def test_returns_none_when_not_cached(self):
        """Return ``None`` when the key is not in the cache."""
        result = get_connectivity_status("node1", "MYSQL")
        assert result is None

    def test_returns_cached_success(self):
        """Return ``True`` for a cached successful check."""
        _connectivity_cache[("node1", "MYSQL")] = (True, None, time.monotonic())
        result = get_connectivity_status("node1", "MYSQL")
        assert result is True

    def test_returns_cached_failure(self):
        """Return ``False`` for a cached failed check."""
        _connectivity_cache[("node1", "MYSQL")] = (
            False,
            "connection refused",
            time.monotonic(),
        )
        result = get_connectivity_status("node1", "MYSQL")
        assert result is False

    def test_returns_none_when_expired(self):
        """Return ``None`` and evict the entry when TTL has passed."""
        expired_time = time.monotonic() - CACHE_TTL - 1
        _connectivity_cache[("node1", "MYSQL")] = (True, None, expired_time)
        result = get_connectivity_status("node1", "MYSQL")
        assert result is None
        assert ("node1", "MYSQL") not in _connectivity_cache


class TestCheckAndWarnConnectivity:
    """Test check_and_warn_connectivity helper."""

    @pytest.mark.asyncio
    async def test_successful_check_caches_true_no_warning(
        self, dummy_request, mock_tasks_api
    ):
        """Cache success and do not flash a warning when check passes."""
        mock_tasks_api.post.return_value = {"success": True, "error": None}

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="MYSQL",
        )

        assert get_connectivity_status("node1", "MYSQL") is True
        assert len(dummy_request.state.messages) == 0

    @pytest.mark.asyncio
    async def test_failed_check_caches_false_and_warns(
        self, dummy_request, mock_tasks_api
    ):
        """Cache failure and flash a warning when check fails."""
        mock_tasks_api.post.return_value = {
            "success": False,
            "error": "connection refused",
        }

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="MYSQL",
        )

        assert get_connectivity_status("node1", "MYSQL") is False
        assert len(dummy_request.state.messages) == 1

    @pytest.mark.asyncio
    async def test_api_unreachable_caches_false_and_warns(
        self, dummy_request, mock_tasks_api
    ):
        """Cache failure and flash a warning when the Tasks API is unreachable."""
        mock_tasks_api.post.side_effect = ConnectionError("timeout")

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=5432,
            service_type="POSTGRESQL",
        )

        assert get_connectivity_status("node1", "POSTGRESQL") is False
        assert len(dummy_request.state.messages) == 1

    @pytest.mark.asyncio
    async def test_success_clears_previous_failure_after_ttl(
        self, dummy_request, mock_tasks_api
    ):
        """Overwrite an expired cached failure with a success on a new check."""
        _connectivity_cache[("node1", "MYSQL")] = (
            False,
            "old failure",
            time.monotonic() - CACHE_TTL - 1,
        )
        mock_tasks_api.post.return_value = {"success": True, "error": None}

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="MYSQL",
        )

        assert get_connectivity_status("node1", "MYSQL") is True

    @pytest.mark.asyncio
    async def test_check_sends_correct_payload(self, dummy_request, mock_tasks_api):
        """Verify the connectivity check request payload matches expectations."""
        mock_tasks_api.post.return_value = {"success": True, "error": None}

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=27017,
            service_type="MONGODB",
        )

        mock_tasks_api.post.assert_awaited_once_with(
            "/connectivity-check/",
            json={
                "target": "node1",
                "host": "10.0.0.1",
                "port": 27017,
                "service_type": "MONGODB",
                "timeout": 10,
            },
        )

    @pytest.mark.asyncio
    async def test_cache_hit_success_short_circuits(
        self, dummy_request, mock_tasks_api
    ):
        """Skip the Tasks API call and warning when a cached success exists."""
        _connectivity_cache[("node1", "MYSQL")] = (True, None, time.monotonic())

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="MYSQL",
        )

        mock_tasks_api.post.assert_not_called()
        assert len(dummy_request.state.messages) == 0

    @pytest.mark.asyncio
    async def test_cache_hit_failure_flashes_cached_error(
        self, dummy_request, mock_tasks_api
    ):
        """Flash the cached error without re-contacting the Tasks API."""
        _connectivity_cache[("node1", "MYSQL")] = (
            False,
            "previously refused",
            time.monotonic(),
        )

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="MYSQL",
        )

        mock_tasks_api.post.assert_not_called()
        assert len(dummy_request.state.messages) == 1
        flashed = next(iter(dummy_request.state.messages))
        assert "previously refused" in flashed.text

    @pytest.mark.asyncio
    async def test_http_exception_uses_upstream_detail(
        self, dummy_request, mock_tasks_api
    ):
        """Use ``HTTPException.detail`` as the flashed error when it is a string."""
        mock_tasks_api.post.side_effect = HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="upstream nomad error"
        )

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="MYSQL",
        )

        assert get_connectivity_status("node1", "MYSQL") is False
        entry = _connectivity_cache[("node1", "MYSQL")]
        assert entry[1] == "upstream nomad error"
        assert len(dummy_request.state.messages) == 1
        flashed = next(iter(dummy_request.state.messages))
        assert "upstream nomad error" in flashed.text

    @pytest.mark.asyncio
    async def test_http_exception_non_string_detail_uses_fallback(
        self, dummy_request, mock_tasks_api
    ):
        """Fall back to a generic error when ``HTTPException.detail`` is non-string."""
        mock_tasks_api.post.side_effect = HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail={"code": "upstream_error"}
        )

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="MYSQL",
        )

        entry = _connectivity_cache[("node1", "MYSQL")]
        assert entry[1] == "Connectivity check failed"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc",
        [
            OSError("refused"),
            TimeoutError("timeout"),
            TimeoutError(),
            ClientError("client error"),
        ],
    )
    async def test_client_errors_cache_false_and_warn(
        self, dummy_request, mock_tasks_api, exc
    ):
        """Cache failure for transport-level errors raised during the POST."""
        mock_tasks_api.post.side_effect = exc

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="MYSQL",
        )

        assert get_connectivity_status("node1", "MYSQL") is False
        entry = _connectivity_cache[("node1", "MYSQL")]
        assert entry[1] == "Could not reach the Tasks API"
        assert len(dummy_request.state.messages) == 1


class TestMaybeCheckConnectivity:
    """Test maybe_check_connectivity guard helper."""

    @pytest.mark.asyncio
    async def test_empty_meta_returns_without_calling(
        self, dummy_request, mock_tasks_api, mocker
    ):
        """Skip the check entirely when ``meta`` is empty."""
        mock_check = mocker.patch(
            "app.sep.connectivity.check_and_warn_connectivity", new_callable=AsyncMock
        )

        await maybe_check_connectivity(dummy_request, mock_tasks_api, {})

        mock_check.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "meta",
        [
            {"target": "node1"},
            {"target": "node1", "_connectivity_host": "10.0.0.1"},
            {
                "target": "node1",
                "_connectivity_host": "10.0.0.1",
                "_connectivity_port": 3306,
            },
            {
                "_connectivity_host": "10.0.0.1",
                "_connectivity_port": 3306,
                "_connectivity_service_type": "MYSQL",
            },
        ],
    )
    async def test_partial_meta_returns_without_calling(
        self, dummy_request, mock_tasks_api, mocker, meta
    ):
        """Skip the check when any of the required meta keys are missing."""
        mock_check = mocker.patch(
            "app.sep.connectivity.check_and_warn_connectivity", new_callable=AsyncMock
        )

        await maybe_check_connectivity(dummy_request, mock_tasks_api, meta)

        mock_check.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_meta_delegates_with_correct_kwargs(
        self, dummy_request, mock_tasks_api, mocker
    ):
        """Delegate to ``check_and_warn_connectivity`` with parsed ``meta`` values."""
        mock_check = mocker.patch(
            "app.sep.connectivity.check_and_warn_connectivity", new_callable=AsyncMock
        )
        meta = {
            "target": "node1",
            "_connectivity_host": "10.0.0.1",
            "_connectivity_port": 3306,
            "_connectivity_service_type": "MYSQL",
        }

        await maybe_check_connectivity(dummy_request, mock_tasks_api, meta)

        mock_check.assert_awaited_once_with(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="MYSQL",
        )


class TestAnnotateTasksWithConnectivity:
    """Test annotate_tasks_with_connectivity helper."""

    def test_annotates_tasks_with_cached_failure(self):
        """Set ``_connectivity_warning`` to ``True`` for tasks with cached failures."""
        _connectivity_cache[("node1", "MYSQL")] = (
            False,
            "refused",
            time.monotonic(),
        )
        tasks = [
            {
                "name": "task1",
                "data": {
                    "meta": {
                        "target": "node1",
                        "_connectivity_service_type": "MYSQL",
                    }
                },
            }
        ]
        annotate_tasks_with_connectivity(tasks)
        assert tasks[0]["_connectivity_warning"] is True

    def test_annotates_tasks_with_cached_success(self):
        """Set ``_connectivity_warning`` to ``False`` for tasks with cached successes."""
        _connectivity_cache[("node1", "MYSQL")] = (True, None, time.monotonic())
        tasks = [
            {
                "name": "task1",
                "data": {
                    "meta": {
                        "target": "node1",
                        "_connectivity_service_type": "MYSQL",
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

    def test_no_annotation_when_not_cached(self):
        """Skip annotation when no cache entry exists."""
        tasks = [
            {
                "name": "task1",
                "data": {
                    "meta": {
                        "target": "node1",
                        "_connectivity_service_type": "MYSQL",
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
        """Annotate tasks in the ``task_info`` format used by ``get_tasks_context``."""
        _connectivity_cache[("node1", "MYSQL")] = (
            False,
            "refused",
            time.monotonic(),
        )
        tasks = [
            {
                "name": "task1",
                "_connectivity_target": "node1",
                "_connectivity_service_type": "MYSQL",
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
