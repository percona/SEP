"""Define tests for the app.core.requests module."""

from http import HTTPStatus

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

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
    )


@pytest.mark.asyncio
async def test_context_manager_open_close(remote_api, base_url):
    """Test the RemoteAPI context manager for opening and closing the session."""
    with aioresponses() as m:
        m.get(base_url, status=200, payload={})

        async with remote_api as api:
            assert isinstance(api.session, ClientSession)
            response = await api.session.get(base_url)
            assert response.status == HTTPStatus.OK

        assert api.session.closed


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
                response = await remote_api.get(full_url)
            elif method == "POST":
                response = await remote_api.post(full_url, json=request_payload)
            elif method == "PUT":
                response = await remote_api.put(full_url, json=request_payload)
            elif method == "PATCH":
                response = await remote_api.patch(full_url, json=request_payload)
            elif method == "DELETE":
                response = await remote_api.delete(full_url)

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
