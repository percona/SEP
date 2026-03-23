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

from unittest.mock import AsyncMock, MagicMock, Mock, patch

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
async def test_stream_yields_content_chunks_and_logs_debug_lifecycle(remote_api):
    """Stream yields aiohttp body chunks and logs start/end at DEBUG."""

    async def body():
        yield b"chunk-a"
        yield b"chunk-b"

    mock_response = MagicMock()
    mock_response.content = body()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch.object(remote_api.logger, "debug") as mock_debug:
        async with remote_api:
            with patch.object(remote_api, "_request", return_value=mock_ctx):
                chunks = [
                    c async for c in remote_api.stream("/stream/path/", method="GET")
                ]

    assert chunks == [b"chunk-a", b"chunk-b"]
    mock_debug.assert_any_call(
        "Stream started path=%s method=%s", "/stream/path/", "GET"
    )
    mock_debug.assert_any_call(
        "Stream ended normally path=%s method=%s", "/stream/path/", "GET"
    )


@pytest.mark.asyncio
async def test_stream_logs_warning_with_exc_info_and_reraises_on_content_error(
    remote_api,
):
    """On iteration failure, stream logs WARNING with exc_info and re-raises."""

    class FailingContent:
        """Async iterator that raises on first chunk."""

        def __aiter__(self):
            return self

        async def __anext__(self):
            msg = "connection reset"
            raise ConnectionResetError(msg)

    mock_response = MagicMock()
    mock_response.content = FailingContent()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch.object(remote_api.logger, "warning") as mock_warning:
        async with remote_api:
            with patch.object(remote_api, "_request", return_value=mock_ctx):
                with pytest.raises(ConnectionResetError, match="connection reset"):
                    [
                        _
                        async for _ in remote_api.stream(
                            "/history/1/logs/", method="GET"
                        )
                    ]

    mock_warning.assert_called_once()
    args, kwargs = mock_warning.call_args
    assert args[0] == "Stream error path=%s method=%s: %s"
    assert args[1] == "/history/1/logs/"
    assert args[2] == "GET"
    assert isinstance(args[3], ConnectionResetError)
    assert kwargs.get("exc_info") is True


@pytest.mark.asyncio
async def test_stream_logs_warning_when_request_context_raises(remote_api):
    """Errors from opening the HTTP context are logged and re-raised."""
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("session failed"))
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch.object(remote_api.logger, "warning") as mock_warning:
        async with remote_api:
            with patch.object(remote_api, "_request", return_value=mock_ctx):
                with pytest.raises(RuntimeError, match="session failed"):
                    [_ async for _ in remote_api.stream("/x/", method="POST")]

    mock_warning.assert_called_once()
    wargs, wkwargs = mock_warning.call_args
    assert wargs[1] == "/x/"
    assert wargs[2] == "POST"
    assert isinstance(wargs[3], RuntimeError)
    assert wkwargs.get("exc_info") is True
