"""Define test fixtures for the SEP app."""

from collections import OrderedDict
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from fastapi import Request
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pytest_mock import MockerFixture

from app.core.requests import RemoteAPI
from app.models import CasdoorUser
from app.sep.deps import (
    get_current_user,
    get_inventory_api,
    get_tasks_api,
    validate_csrf,
)
from app.sep.main import sep_app


@pytest.fixture
def test_client(regular_user: CasdoorUser) -> TestClient:
    """Create an authenticated test client for the app."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest_asyncio.fixture
async def async_test_client(regular_user: CasdoorUser) -> AsyncClient:
    """Create an authenticated async test client for the app."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user

    transport = ASGITransport(app=sep_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    sep_app.dependency_overrides = {}


@pytest.fixture
def dummy_request() -> Request:
    """Create a dummy Request with a messages attribute in its state."""
    scope = {"type": "http", "headers": [], "client": ("127.0.0.1", "80"), "path": "/"}
    req = Request(scope)
    req.state.messages = OrderedDict()
    return req


@pytest.fixture
def mock_task_api_dep(mock_remote_api: RemoteAPI) -> AsyncMock:
    """Mock the TaskAPI dependency."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_inventory_api_dep(mock_remote_api: RemoteAPI) -> AsyncMock:
    """Mock the InventoryAPI dependency."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_inventory_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_get_username_mapping(mocker: MockerFixture) -> Mock:
    """Mock the TaskDep dependency."""
    return mocker.patch(
        "app.sep.deps.get_username_mapping",
        return_value={"12345678-1234-5678-9abc-123456789012": "test-user"},
    )
