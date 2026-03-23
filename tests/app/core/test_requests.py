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
from aiohttp import ClientResponseError, ClientSession, ContentTypeError
from aioresponses import aioresponses
from fastapi import HTTPException, status
from pydantic import HttpUrl

from app.core.requests import RemoteAPI
from app.core.requests.remote_api import BaseRemoteAPI


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


@pytest.fixture(autouse=True)
def clear_ssl_context_cache():
    """Reset SSL context lru_cache so certfile tests do not share state."""
    BaseRemoteAPI.create_ssl_context.cache_clear()
    yield
    BaseRemoteAPI.create_ssl_context.cache_clear()


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


def test_base_remote_api_hash_stable():
    """BaseRemoteAPI instances with the same config share the same hash."""
    a = BaseRemoteAPI(endpoint=HttpUrl("http://example.com/"))
    b = BaseRemoteAPI(endpoint=HttpUrl("http://example.com/"))
    assert hash(a) == hash(b)


def test_base_remote_api_headers_default():
    """BaseRemoteAPI exposes empty default headers."""
    api = BaseRemoteAPI(endpoint=HttpUrl("http://example.com/"))
    assert api.headers == {}


def test_base_url_strips_api_path():
    """base_url drops the API path segment from the origin."""
    api = RemoteAPI(endpoint=HttpUrl("http://localhost:8000/api"))
    assert api.base_path == "/api"
    assert api.base_url == "http://localhost:8000"


def test_prepare_path_trailing_slash():
    """prepare_path preserves a trailing slash on the requested path."""
    api = RemoteAPI(endpoint=HttpUrl("http://localhost:8000/api/"))
    assert api.prepare_path("v1/users/") == "/api/v1/users/"


def test_prepare_path_when_base_path_is_root():
    """When the endpoint path is root, paths join against ``/``."""
    api = RemoteAPI(endpoint=HttpUrl("http://localhost:8000/"))
    assert api.prepare_path("items") == "/items"


@pytest.mark.asyncio
async def test_aexit_when_session_already_closed(remote_api):
    """Second __aexit__ hits the branch when the session is already cleared."""
    async with remote_api:
        pass
    await remote_api.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_open_and_close(remote_api, base_url):
    """open() / close() mirror async context manager lifecycle."""
    with aioresponses() as m:
        m.get(base_url, status=status.HTTP_200_OK, payload={})
        await remote_api.open()
        assert remote_api.session is not None
        await remote_api.session.get("/")
        await remote_api.close()
        assert remote_api.session is None


@pytest.mark.asyncio
async def test_nested_async_with_reuses_session(remote_api):
    """Nested async with does not create a second ClientSession."""
    with aioresponses() as m:
        m.get("http://localhost:8000/", status=status.HTTP_200_OK, payload={})
        async with remote_api:
            s1 = remote_api.session
            async with remote_api:
                assert remote_api.session is s1


@pytest.mark.asyncio
async def test_extra_headers_context_and_merge(remote_api, base_url):
    """extra_headers, set/reset, and per-request headers merge in _request."""
    with aioresponses() as m:
        m.get(
            f"{base_url}merge",
            status=status.HTTP_200_OK,
            payload={"ok": True},
        )

        async with remote_api:
            with remote_api.extra_headers({"X-Extra": "1"}):
                token = remote_api.set_extra_headers({"X-Temp": "2"})
                try:
                    await remote_api.get("merge", headers={"X-Base": "a"})
                finally:
                    remote_api.reset_extra_headers(token)


@pytest.mark.asyncio
async def test_session_setter(remote_api):
    """Session setter replaces the aiohttp ClientSession used for requests."""
    mock_session = AsyncMock(spec=ClientSession)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = AsyncMock(status=status.HTTP_200_OK)
    mock_cm.__aexit__.return_value = None
    mock_session.request.return_value = mock_cm

    async with remote_api:
        remote_api.session = mock_session
        async with remote_api._request("GET", "/x") as resp:
            assert resp.status == status.HTTP_200_OK
        mock_session.request.assert_called()


@pytest.mark.asyncio
async def test_stream_yields_chunks(remote_api, base_url):
    """stream() yields raw bytes from the response body iterator."""
    body = b"chunk1\nchunk2\n"
    with aioresponses() as m:
        m.get(f"{base_url}stream", body=body)
        async with remote_api:
            out = [c async for c in remote_api.stream("/stream")]
    assert b"".join(out) == body


@pytest.mark.asyncio
async def test_auth_context(remote_api, base_url):
    """auth() wraps extra_headers with an Authorization value."""
    with aioresponses() as m:
        m.get(f"{base_url}auth", status=status.HTTP_200_OK, payload={})
        async with remote_api:
            with remote_api.auth("secret-token"):
                await remote_api.get("auth")


def test_create_ssl_context_without_certfile():
    """create_ssl_context returns a context without load_cert_chain when no cert."""
    ctx = BaseRemoteAPI.create_ssl_context()
    assert ctx is not None


def test_create_ssl_context_with_certfile(monkeypatch):
    """When certfile is set, load_cert_chain is invoked on the SSL context."""
    mock_ctx = Mock()

    def fake_create_default_context(*_args: object, **_kwargs: object) -> Mock:
        return mock_ctx

    monkeypatch.setattr(
        "app.core.requests.remote_api.create_default_context",
        fake_create_default_context,
    )
    BaseRemoteAPI.create_ssl_context.cache_clear()
    result = BaseRemoteAPI.create_ssl_context(
        cafile=None,
        certfile="/fake/cert.pem",
        keyfile="/fake/key.pem",
    )
    mock_ctx.load_cert_chain.assert_called_once_with(
        certfile="/fake/cert.pem",
        keyfile="/fake/key.pem",
    )
    assert result is mock_ctx


@pytest.mark.asyncio
async def test_request_content_type_error(remote_api):
    """Non-JSON bodies raise HTTPException when json() raises ContentTypeError."""
    mock_response = AsyncMock()
    mock_response.json = AsyncMock(
        side_effect=ContentTypeError(
            request_info=None,
            history=(),
            status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    )
    mock_response.status = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    mock_response.content = b"not-json"

    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_response
    mock_context_manager.__aexit__.return_value = None

    with patch.object(remote_api, "_request", return_value=mock_context_manager):
        with pytest.raises(HTTPException) as exc_info:
            await remote_api.request("GET", "/bad-content-type")
        assert exc_info.value.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        assert exc_info.value.detail == "An unexpected error occurred on the server."


@pytest.mark.asyncio
async def test_request_client_response_error_without_error_code_header(remote_api):
    """ClientResponseError omits X-Error-Code when error_code_key is unset."""
    mock_response = AsyncMock()
    mock_response.json.return_value = {"detail": "gone"}
    mock_response.status = status.HTTP_410_GONE
    error = ClientResponseError(
        request_info=None,
        history=None,
        status=status.HTTP_410_GONE,
        message="Gone",
    )
    mock_response.raise_for_status = Mock(side_effect=error)

    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_response
    mock_context_manager.__aexit__.return_value = None

    no_code_api = remote_api.model_copy(update={"error_code_key": None})

    with patch.object(no_code_api, "_request", return_value=mock_context_manager):
        with pytest.raises(HTTPException) as exc_info:
            await no_code_api.request("GET", "/gone")
        assert exc_info.value.status_code == status.HTTP_410_GONE
        assert exc_info.value.headers is None


@pytest.mark.asyncio
async def test_stream_yields_content_chunks_and_logs_debug_lifecycle(remote_api):
    """Stream yields aiohttp body chunks and logs start/end at DEBUG."""

    async def body():
        yield b"chunk-a"
        yield b"chunk-b"

    mock_response = MagicMock()
    mock_response.status = status.HTTP_200_OK
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
    mock_response.status = status.HTTP_200_OK
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
