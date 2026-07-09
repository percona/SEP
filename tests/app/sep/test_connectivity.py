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

from collections import OrderedDict
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError
from fastapi import HTTPException, Request, status
from starlette.datastructures import FormData

from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import (
    _fetch_connectivity_result,
    _LATEST_RESULTS,
    _record_latest_result,
    annotate_tasks_with_connectivity,
    check_and_warn_connectivity,
    get_check_connectivity_flag,
    maybe_check_connectivity,
)


def _make_request_with_form(form_data: FormData) -> Request:
    """Build a minimal ``Request`` whose ``form()`` returns ``form_data``.

    :param form_data: Pre-parsed form data to inject into the request.
    :type form_data: FormData
    :return: A bare ``Request`` with the supplied form data already cached.
    :rtype: Request
    """
    scope = {
        "type": "http",
        "headers": [],
        "client": ("127.0.0.1", 80),
        "path": "/",
    }
    req = Request(scope)
    req._form = form_data
    return req


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


class TestCheckAndWarnConnectivity:
    """Test check_and_warn_connectivity helper."""

    @pytest.mark.asyncio
    async def test_successful_check_no_warning(self, dummy_request, mock_tasks_api):
        """Cache success and do not flash a warning when check passes."""
        mock_tasks_api.post.return_value = {"success": True, "error": None}

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="mysql",
        )

        assert _LATEST_RESULTS[("node1", "mysql")] is True
        assert len(dummy_request.state.messages) == 0

    @pytest.mark.asyncio
    async def test_failed_check_warns(self, dummy_request, mock_tasks_api):
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
            service_type="mysql",
        )

        assert _LATEST_RESULTS[("node1", "mysql")] is False
        assert len(dummy_request.state.messages) == 1
        flashed = next(iter(dummy_request.state.messages))
        assert "10.0.0.1:3306" in flashed.text
        assert "mysql" in flashed.text
        assert "node1" in flashed.text
        assert "connection refused" in flashed.text

    @pytest.mark.asyncio
    async def test_failed_check_flash_points_to_log(
        self, dummy_request, mock_tasks_api
    ):
        """Include a task-history pointer in the flash so the log is findable.

        When the API returns a ``task_history_id`` it must appear in the flash
        text so operators can inspect why the check failed.
        """
        mock_tasks_api.post.return_value = {
            "success": False,
            "error": "Connectivity check timed out after 30s",
            "task_history_id": 777,
        }

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="mysql",
        )

        flashed = next(iter(dummy_request.state.messages))
        assert "777" in flashed.text

    @pytest.mark.asyncio
    async def test_api_unreachable_warns(self, dummy_request, mock_tasks_api):
        """Cache failure and flash a warning when the Tasks API is unreachable."""
        mock_tasks_api.post.side_effect = ConnectionError("timeout")

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=5432,
            service_type="postgresql",
        )

        assert _LATEST_RESULTS[("node1", "postgresql")] is False
        assert len(dummy_request.state.messages) == 1
        flashed = next(iter(dummy_request.state.messages))
        assert "10.0.0.1:5432" in flashed.text
        assert "postgresql" in flashed.text
        assert "node1" in flashed.text
        assert "Could not reach the Tasks API" in flashed.text

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
            service_type="mongodb",
        )

        mock_tasks_api.post.assert_awaited_once_with(
            "/connectivity-check/",
            json={
                "target": "node1",
                "host": "10.0.0.1",
                "port": 27017,
                "service_type": "mongodb",
                "timeout": 20,
            },
        )

    @pytest.mark.asyncio
    async def test_cache_hit_short_circuits(self, dummy_request, mock_tasks_api):
        """Skip the Tasks API call when the alru_cache already has a hit."""
        mock_tasks_api.post.return_value = {"success": True, "error": None}

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="mysql",
        )
        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="mysql",
        )

        mock_tasks_api.post.assert_awaited_once()
        assert len(dummy_request.state.messages) == 0

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
            service_type="mysql",
        )

        assert _LATEST_RESULTS[("node1", "mysql")] is False
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
            service_type="mysql",
        )

        assert _LATEST_RESULTS[("node1", "mysql")] is False
        flashed = next(iter(dummy_request.state.messages))
        assert "Connectivity check failed" in flashed.text

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
    async def test_client_errors_warn(self, dummy_request, mock_tasks_api, exc):
        """Cache failure for transport-level errors raised during the POST."""
        mock_tasks_api.post.side_effect = exc

        await check_and_warn_connectivity(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="mysql",
        )

        assert _LATEST_RESULTS[("node1", "mysql")] is False
        flashed = next(iter(dummy_request.state.messages))
        assert "Could not reach the Tasks API" in flashed.text


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
                "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
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
            "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
        }

        await maybe_check_connectivity(dummy_request, mock_tasks_api, meta)

        mock_check.assert_awaited_once_with(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="mysql",
        )

    @pytest.mark.asyncio
    async def test_opt_out_skips_check_and_warn(
        self, dummy_request, mock_tasks_api, mocker
    ):
        """Skip the Tasks API call and the cache write when opted out."""
        mock_check = mocker.patch(
            "app.sep.connectivity.check_and_warn_connectivity", new_callable=AsyncMock
        )
        meta = {
            "target": "node1",
            "_connectivity_host": "10.0.0.1",
            "_connectivity_port": 3306,
            "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
        }

        await maybe_check_connectivity(
            dummy_request, mock_tasks_api, meta, check_connectivity=False
        )

        mock_check.assert_not_called()
        assert _LATEST_RESULTS == {}

    @pytest.mark.asyncio
    async def test_opt_out_preserves_existing_cache_entry(
        self, dummy_request, mock_tasks_api, mocker
    ):
        """Preserve an existing ``_LATEST_RESULTS`` entry when opted out."""
        mocker.patch(
            "app.sep.connectivity.check_and_warn_connectivity", new_callable=AsyncMock
        )
        _record_latest_result("node1", "mysql", success=True)
        meta = {
            "target": "node1",
            "_connectivity_host": "10.0.0.1",
            "_connectivity_port": 3306,
            "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
        }

        await maybe_check_connectivity(
            dummy_request, mock_tasks_api, meta, check_connectivity=False
        )

        assert _LATEST_RESULTS[("node1", "mysql")] is True
        assert len(_LATEST_RESULTS) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cached_success", [True, False])
    async def test_opt_out_preserves_existing_failure_entry(
        self, dummy_request, mock_tasks_api, mocker, cached_success
    ):
        """Preserve both success and failure cache entries when opted out."""
        mocker.patch(
            "app.sep.connectivity.check_and_warn_connectivity", new_callable=AsyncMock
        )
        _record_latest_result("node1", "mysql", success=cached_success)
        meta = {
            "target": "node1",
            "_connectivity_host": "10.0.0.1",
            "_connectivity_port": 3306,
            "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
        }

        await maybe_check_connectivity(
            dummy_request, mock_tasks_api, meta, check_connectivity=False
        )

        assert _LATEST_RESULTS[("node1", "mysql")] is cached_success

    @pytest.mark.asyncio
    async def test_opt_in_explicit_true_still_runs_check(
        self, dummy_request, mock_tasks_api, mocker
    ):
        """Run the check when ``check_connectivity=True`` is passed explicitly."""
        mock_check = mocker.patch(
            "app.sep.connectivity.check_and_warn_connectivity", new_callable=AsyncMock
        )
        meta = {
            "target": "node1",
            "_connectivity_host": "10.0.0.1",
            "_connectivity_port": 3306,
            "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
        }

        await maybe_check_connectivity(
            dummy_request, mock_tasks_api, meta, check_connectivity=True
        )

        mock_check.assert_awaited_once_with(
            dummy_request,
            mock_tasks_api,
            target="node1",
            host="10.0.0.1",
            port=3306,
            service_type="mysql",
        )

    @pytest.mark.asyncio
    async def test_opt_out_with_incomplete_meta_returns_cleanly(
        self, dummy_request, mock_tasks_api, mocker
    ):
        """Short-circuit before meta extraction when opted out."""
        mock_check = mocker.patch(
            "app.sep.connectivity.check_and_warn_connectivity", new_callable=AsyncMock
        )
        meta = {"target": "node1"}

        await maybe_check_connectivity(
            dummy_request, mock_tasks_api, meta, check_connectivity=False
        )

        mock_check.assert_not_called()
        assert _LATEST_RESULTS == {}


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
        """Annotate tasks in the ``task_info`` format used by ``get_tasks_context``."""
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


class TestGetCheckConnectivityFlag:
    """Test get_check_connectivity_flag form-coercion helper."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("on", True),
            ("true", True),
            ("True", True),
            ("1", True),
            ("yes", True),
            ("off", False),
            ("false", False),
            ("0", False),
            ("no", False),
            ("", False),
            ("garbage", False),
        ],
    )
    async def test_parses_checkbox_values(self, raw, expected):
        """Coerce form-submitted ``check_connectivity`` strings via Pydantic."""
        request = _make_request_with_form(FormData([("check_connectivity", raw)]))
        assert await get_check_connectivity_flag(request) is expected

    @pytest.mark.asyncio
    async def test_returns_false_when_field_missing(self):
        """Return ``False`` when ``check_connectivity`` is absent from the form."""
        request = _make_request_with_form(FormData())
        assert await get_check_connectivity_flag(request) is False
