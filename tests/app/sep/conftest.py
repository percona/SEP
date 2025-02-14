"""Define test fixtures for the SEP app."""

import pytest
import pytest_asyncio
from fastapi import Request
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.models import CasdoorUser
from app.sep.deps import get_current_user, validate_csrf
from app.sep.main import sep_app


@pytest.fixture
def test_client(regular_user: CasdoorUser) -> TestClient:
    """Create an authenticated test client for the app."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    yield TestClient(sep_app)
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
    scope = {"type": "http", "headers": [], "client": ("127.0.0.1", "80")}
    req = Request(scope)
    req.state.messages = []
    return req
