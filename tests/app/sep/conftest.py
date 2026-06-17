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

"""Define test fixtures for the SEP app."""

from collections import OrderedDict
from collections.abc import Iterator
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from fastapi import Request
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy_celery_beat.models import PeriodicTask
from sqlmodel import SQLModel

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.requests import RemoteAPI
from app.core.utils import json_serializer
from app.models import CasdoorUser
from app.sep.deps import (
    get_api_authenticated_user,
    get_current_user,
    get_inventory_api,
    get_session,
    get_tasks_api,
    require_bearer_for_unsafe_methods,
    validate_csrf,
)
from app.sep.main import sep_app


@pytest_asyncio.fixture(name="session")
async def session_fixture() -> AsyncSession:
    """Create an async db session for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    async with async_session_maker() as session:
        yield session


@pytest_asyncio.fixture(name="celery_beat_session")
async def celery_beat_session_fixture() -> AsyncSession:
    """Create an async db session backed by the celery-beat tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"celery_schema": None})
    metadata = PeriodicTask.__table__.metadata
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    async with async_session_maker() as session:
        yield session


@pytest.fixture
def test_client(regular_user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Yield an authenticated cookie-auth TestClient for the SEP app.

    Overrides ``require_bearer_for_unsafe_methods`` so cookie-only JSON
    mutations under ``/api/plugins/*`` are not blocked by the framework
    Bearer gate. Plugin-local ``test_client`` overrides MUST
    mirror this override; see :func:`api_admin_client_no_bearer` for the
    negative-path fixture that leaves the gate intact.

    ``get_session`` is overridden to the in-memory ``session`` so the
    ``require_app_enabled`` route guard reads an isolated, empty ``appstate``
    table (no rows -> every app enabled) instead of a shared, order-dependent
    DB. Tests that exercise the disabled path override ``get_session`` again
    with a session that carries an ``enabled=False`` row.
    """
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def api_admin_client_no_bearer(admin_user: CasdoorUser) -> TestClient:
    """Yield a cookie-auth admin TestClient with the Bearer gate intact.

    Mirrors :func:`test_client` but deliberately leaves
    ``require_bearer_for_unsafe_methods`` un-overridden, so cookie-only
    JSON mutations to ``/api/plugins/*`` are rejected by the framework
    Bearer gate. Use in tests that assert the 401 path.
    """
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: admin_user
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def unauthenticated_client() -> Iterator[TestClient]:
    """Yield a test client with authentication dependency overrides cleared."""
    previous = sep_app.dependency_overrides
    sep_app.dependency_overrides = {}
    try:
        yield TestClient(sep_app, raise_server_exceptions=False)
    finally:
        sep_app.dependency_overrides = previous


@pytest_asyncio.fixture
async def async_test_client(regular_user: CasdoorUser) -> AsyncClient:
    """Yield an authenticated async cookie-auth client for the SEP app.

    See :func:`test_client` for the Bearer-gate override rationale.
    """
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user

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
    mock.get.return_value = {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 50,
    }
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
