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

"""Define tests for the app.core.requests module."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp import ClientResponseError, ClientSession
from aioresponses import aioresponses
from fastapi import HTTPException, status

from app.core.requests import RemoteAPI


@pytest.fixture
def base_url():
    """Fixture to provide the base URL for the API."""
    return "http://localhost:8000/"


@pytest.fixture
def api_key():
    """Fixture to provide a test API key."""
    return "test_api_key"


@pytest.fixture
def remote_api(base_url):
    """Fixture to initialize the RemoteAPI instance."""
    return RemoteAPI(
        endpoint=base_url,
        api_key="test_api_key",
        auth_scheme="Bearer",
        error_detail_key="detail",
        error_code_key="code",
    )


@pytest.mark.asyncio
async def test_context_manager_open_close(remote_api, base_url):
    """Test the RemoteAPI context manager for opening and closing the session."""
    with aioresponses() as m:
        m.get(base_url, status=200, payload={})

        assert remote_api.session is None

        async with remote_api:
            assert remote_api.session is not None
            assert isinstance(remote_api.session, ClientSession)
            response = await remote_api.session.get("/")
            assert response.status == status.HTTP_200_OK

        assert remote_api.session is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method, test_path, request_payload, response_data, status_code"),  # noqa: PT006
    [
        ("GET", "test/get", None, {"key": "value"}, 200),
        ("POST", "test/post", {"input": "data"}, {"result": "success"}, 201),
        ("PUT", "test/put", {"update": "value"}, {"result": "updated"}, 200),
        ("PATCH", "test/patch", {"patch": "value"}, {"result": "patched"}, 200),
        ("DELETE", "test/delete", None, {"result": "deleted"}, 200),
    ],
)
async def test_request_methods(
    remote_api, base_url, method, test_path, request_payload, response_data, status_code
):
    """Test various HTTP request methods supported by RemoteAPI."""
    full_url = base_url + test_path

    with aioresponses() as m:
        m.add(full_url, method, status=status_code, payload=response_data)

        async with remote_api:
            if method == "GET":
                response = await remote_api.get(test_path)
            elif method == "POST":
                response = await remote_api.post(test_path, json=request_payload)
            elif method == "PUT":
                response = await remote_api.put(test_path, json=request_payload)
            elif method == "PATCH":
                response = await remote_api.patch(test_path, json=request_payload)
            elif method == "DELETE":
                response = await remote_api.delete(test_path)

            assert response == response_data


@pytest.mark.parametrize(
    ("endpoint, input_path, expected_path"),  # noqa: PT006
    [
        ("http://localhost:8000/", "users", "/users"),
        ("http://localhost:8000/api", "v1/users", "/api/v1/users"),
    ],
)
def test_prepare_path(endpoint: str, input_path: str, expected_path: str):
    """Test the path preparation logic in RemoteAPI."""
    remote_api = RemoteAPI(
        endpoint=endpoint,
        api_key="test_api_key",
        auth_scheme="Bearer",
    )
    assert remote_api.prepare_path(input_path) == expected_path


@pytest.mark.asyncio
async def test_request_error(remote_api):
    """Test handling of errors with detailed error response."""
    conflict_error_msg = "Task with the same name already exists."
    conflict_error_code = "DUP_ERROR"
    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "detail": conflict_error_msg,
        "code": conflict_error_code,
    }
    mock_response.status = status.HTTP_409_CONFLICT
    error = ClientResponseError(
        request_info=None,
        history=None,
        status=status.HTTP_409_CONFLICT,
        message="Conflict",
    )
    mock_response.raise_for_status = Mock(side_effect=error)

    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_response
    mock_context_manager.__aexit__.return_value = None

    with patch.object(remote_api, "_request", return_value=mock_context_manager):
        with pytest.raises(HTTPException) as exc_info:
            await remote_api.request("GET", "/non-existent-path")
        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
        assert exc_info.value.detail == conflict_error_msg
        assert exc_info.value.headers == {"X-Error-Code": conflict_error_code}


@pytest.mark.asyncio
async def test_internal_request_log_redacts_sensitive_kwargs(remote_api):
    """Ensure request debug logs mask passwords and authorization headers."""
    mock_response = AsyncMock()
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_response
    mock_context_manager.__aexit__.return_value = None

    async with remote_api:
        with (
            patch.object(remote_api.session, "request", return_value=mock_context_manager),
            patch.object(remote_api.logger, "debug") as debug_mock,
        ):
            async with remote_api._request(
                "POST",
                "/nomad/variables/",
                headers={"Authorization": "Bearer super-secret-token"},
                json={
                    "data": {
                        "config": {
                            "username": "alice",
                            "password": "plain-password",
                        }
                    }
                },
            ):
                pass

    logged_kwargs = debug_mock.call_args.args[4]
    assert logged_kwargs["headers"]["Authorization"] == "***"
    assert logged_kwargs["json"]["data"]["config"]["password"] == "***"


@pytest.mark.asyncio
async def test_internal_request_log_redacts_json_strings(remote_api):
    """Ensure request debug logs sanitize JSON-encoded secret values."""
    mock_response = AsyncMock()
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_response
    mock_context_manager.__aexit__.return_value = None

    async with remote_api:
        with (
            patch.object(remote_api.session, "request", return_value=mock_context_manager),
            patch.object(remote_api.logger, "debug") as debug_mock,
        ):
            async with remote_api._request(
                "PUT",
                "/v1/var/sep/runtime/mum/test",
                json={
                    "Items": {
                        "config": '{"action":"create_user","password":"p@ssw0rd"}',
                    }
                },
            ):
                pass

    logged_kwargs = debug_mock.call_args.args[4]
    assert logged_kwargs["json"]["Items"]["config"]["password"] == "***"
