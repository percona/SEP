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

"""Define test fixtures."""

import inspect
import os
import socket
import threading
from collections.abc import AsyncGenerator, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from unittest.mock import AsyncMock, Mock

import aioresponses.core
import pytest
import pytest_asyncio
from aiohttp import ClientResponse
from faker import Faker
from fastapi import Request, status
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy_celery_beat.models import PeriodicTask
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.alerts.config import alert_settings
from app.core.auth.base import BaseAuthProvider
from app.core.auth.config import get_active_auth_provider
from app.core.auth.models import OAuthToken
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.auth.providers.grafana.provider import GrafanaAuthProvider
from app.core.config import settings
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.health import HEALTH_PATH
from app.core.requests import RemoteAPI
from app.core.utils import json_serializer
from app.inventory.models import ServiceTypeEnum
from app.sep.config import sep_settings
from app.sep.deps import (
    get_current_user,
    get_inventory_api,
    get_session,
    get_tasks_api,
    require_bearer_for_unsafe_methods,
)
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.main import sep_app
from app.sep.snippets.config import snippets_settings
from app.tasks.anonymizer.config import anonymizer_settings
from app.tasks.config import tasks_settings
from tests.app.factories import (
    CasdoorUserFactory,
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
    OAuthTokenFactory,
)

# aiohttp 3.14 made ``stream_writer`` a required arg of ``ClientResponse``, but
# aioresponses (<=0.7.8) still constructs mocks without it. Default it here until
# aioresponses ships a fix; guarded on the param so it's a no-op on aiohttp < 3.14.
if "stream_writer" in inspect.signature(ClientResponse.__init__).parameters:

    class _StubStreamWriter:
        # aioresponses passes writer=None, so ClientResponse reads output_size.
        output_size: int = 0

    class _CompatClientResponse(ClientResponse):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.setdefault("stream_writer", _StubStreamWriter())
            super().__init__(*args, **kwargs)

    aioresponses.core.ClientResponse = _CompatClientResponse


class HealthProbeServer:
    """Drive a real HTTP listener on loopback answering the shared health path.

    The readiness gate in :mod:`app.core.health` polls over a real socket, so the
    failures worth covering -- connection refused, a listener that accepts and
    never answers, a host-header rejection -- only reproduce against a real
    listener. The port is reserved and released in ``__init__`` so a test can
    probe a closed port before calling :meth:`start`.
    """

    def __init__(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            self.port: int = probe.getsockname()[1]
        self.statuses: list[int] = []
        self.default_status: int = status.HTTP_200_OK
        self.headers_to_send: dict[str, str] = {}
        self.required_host: str | None = None
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.listening = threading.Event()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            """Answer the health path from the controller's script."""

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
                """Answer with the next scripted status, honouring the host rule."""
                server.requests.append((self.path, dict(self.headers.items())))
                if self.path != HEALTH_PATH:
                    self.send_error(status.HTTP_404_NOT_FOUND)
                    return
                if (
                    server.required_host is not None
                    and self.headers.get("Host", "").split(":")[0]
                    != server.required_host
                ):
                    self.send_error(status.HTTP_400_BAD_REQUEST)
                    return
                status_code = (
                    server.statuses.pop(0) if server.statuses else server.default_status
                )
                self.send_response(status_code)
                for name, value in server.headers_to_send.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args: Any, **kwargs: Any) -> None:
                """Silence the handler's stderr access log."""

        return Handler

    def start(self) -> None:
        """Begin serving on the reserved port."""
        for _ in range(5):
            try:
                self._server = HTTPServer(
                    ("127.0.0.1", self.port), self._build_handler()
                )
            except OSError:
                continue
            break
        else:
            pytest.skip(f"could not bind 127.0.0.1:{self.port} for a probe test")
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.listening.set()

    def stop(self) -> None:
        """Stop serving and join the serving thread."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


@pytest.fixture(name="health_probe_server")
def health_probe_server_fixture() -> Iterator[HealthProbeServer]:
    """Yield a controller for a real loopback listener on the health path."""
    server = HealthProbeServer()
    yield server
    server.stop()


@pytest.fixture(scope="session", autouse=True)
def _disable_settings_override_refresher_for_session() -> Iterator[None]:
    """Disable the DB-override background refresher for the entire test session.

    ``TestClient(...)`` enters each FastAPI app's lifespan, which would otherwise
    open a session against the production engine via the real refresher. We use
    ``pytest.MonkeyPatch()`` directly (not the function-scoped ``monkeypatch``
    fixture, which raises ``ScopeMismatch`` at session scope) so the patch
    survives across tests. Tests that need to exercise the refresher re-enable
    it locally via the function-scoped ``monkeypatch`` fixture.
    """
    mp = pytest.MonkeyPatch()
    mp.setattr(settings.SETTINGS_OVERRIDE, "REFRESHER_ENABLED", False)
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def _override_snapshot_cleared() -> None:
    """Clear every wired ``OverridableSettingsProxy`` snapshot before each test.

    Tests that monkey-patch ``*_settings`` attributes assume the proxy's
    ``__getattr__`` falls through to the wrapped Pydantic instance. An active
    snapshot entry would shadow the monkey-patched value and confuse the test.
    """
    settings._set_snapshot({})  # noqa: SLF001
    sep_settings._set_snapshot({})  # noqa: SLF001
    tasks_settings._set_snapshot({})  # noqa: SLF001
    snippets_settings._set_snapshot({})  # noqa: SLF001
    alert_settings._set_snapshot({})  # noqa: SLF001
    anonymizer_settings._set_snapshot({})  # noqa: SLF001


@pytest.fixture(scope="session")
def faker() -> Faker:
    """Provide a Faker instance for generating fake data."""
    return Faker()


@pytest.fixture
def casdoor_allowed_issuer() -> str:
    """Provide a Casdoor allowed issuer URL."""
    return "https://allowed-issuer.com"


@pytest.fixture
def casdoor_disallowed_issuer() -> str:
    """Provide a Casdoor disallowed issuer URL."""
    return "https://disallowed-issuer.com"


@pytest.fixture
def casdoor_client_id() -> str:
    """Provide a fake Casdoor client ID."""
    return "test-client-id"


@pytest.fixture
def valid_username() -> str:
    """Provide a valid username for testing."""
    return "valid-username"


@pytest.fixture
def casdoor_token_payload_data(
    casdoor_allowed_issuer: str,
    casdoor_client_id: str,
    valid_username: str,
    faker: Faker,
) -> dict[str, Any]:
    """Provide mock data for a Casdoor token payload."""
    return {
        "iss": casdoor_allowed_issuer,
        "sub": faker.pystr(),
        "aud": [casdoor_client_id],
        "exp": round(faker.unix_time(end_datetime="+30d", start_datetime="+7d")),
        "nbf": round(faker.unix_time(end_datetime="-1d", start_datetime="-3d")),
        "jti": faker.pystr(),
        "username": valid_username,
        "active": True,
    }


@pytest.fixture
def casdoor_user_data(valid_username: str, faker: Faker) -> dict[str, Any]:
    """Provide mock data for a Casdoor user."""
    return {
        "id": faker.uuid4(),
        "username": valid_username,
        "email": faker.email(),
        "first_name": faker.first_name(),
        "last_name": faker.last_name(),
        "is_admin": False,
        "created_time": faker.date_time().isoformat(),
        "updated_time": "",
        "owner": "organization",
        "is_forbidden": False,
        "is_deleted": False,
    }


@pytest.fixture(scope="class")
def oauth_token() -> OAuthToken:
    """Provide a mock OAuthToken instance."""
    return OAuthTokenFactory.build()


@pytest.fixture
def refresh_token() -> str:
    """Provide a mock refresh token."""
    return "test_refresh_token"


@pytest.fixture
def casdoor_mock(
    casdoor_token_payload_data: dict[str, Any],
    oauth_token: OAuthToken,
    refresh_token: str,
    casdoor_user_data: dict[str, Any],
    mocker: MockerFixture,
) -> BaseAuthProvider:
    """Mock CasdoorSDK methods to simulate Casdoor service interactions."""
    mocker.patch(
        "app.core.auth.providers.casdoor.sdk.CasdoorSDK.introspect_token",
        new=mocker.AsyncMock(return_value=casdoor_token_payload_data),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.sdk.CasdoorSDK.get_access_token",
        new=mocker.AsyncMock(return_value=oauth_token.model_dump()),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.sdk.CasdoorSDK.refresh_token_request",
        new=mocker.AsyncMock(return_value=oauth_token.model_dump()),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.sdk.CasdoorSDK.get_token",
        new=mocker.AsyncMock(return_value={"data": {"refreshToken": refresh_token}}),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.sdk.CasdoorSDK.get_user",
        new=mocker.AsyncMock(return_value=casdoor_user_data),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.sdk.CasdoorSDK.get_users",
        new=mocker.AsyncMock(return_value=[casdoor_user_data]),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.sdk.CasdoorSDK.delete_token",
        new=mocker.AsyncMock(return_value=True),
    )
    return get_active_auth_provider()


@pytest.fixture
def grafana_service_account_token() -> str:
    """Provide a fake Grafana service-account token."""
    return "test-service-account-token"


@pytest.fixture
def grafana_user_record(valid_username: str, faker: Faker) -> dict[str, Any]:
    """Provide a mock Grafana ``/api/user`` record."""
    return {
        "id": faker.random_int(min=1),
        "login": valid_username,
        "email": faker.email(),
        "isGrafanaAdmin": False,
    }


@pytest.fixture
def grafana_user_orgs() -> list[dict[str, Any]]:
    """Provide a mock Grafana ``/api/user/orgs`` payload."""
    return [{"orgId": 1, "name": "Main Org.", "role": "Viewer"}]


@pytest.fixture
def grafana_org_users(valid_username: str, faker: Faker) -> list[dict[str, Any]]:
    """Provide a mock Grafana ``/api/org/users`` payload."""
    return [
        {
            "userId": faker.random_int(min=1),
            "login": valid_username,
            "email": faker.email(),
            "role": "Viewer",
        }
    ]


@pytest.fixture
def grafana_provider(grafana_service_account_token: str) -> GrafanaAuthProvider:
    """Provide a ``GrafanaAuthProvider`` built with test config."""
    return GrafanaAuthProvider(
        endpoint="https://grafana.example.com",
        service_account_token=grafana_service_account_token,
    )


@pytest.fixture
def grafana_mock(
    grafana_provider: GrafanaAuthProvider,
    grafana_user_record: dict[str, Any],
    grafana_user_orgs: list[dict[str, Any]],
    grafana_org_users: list[dict[str, Any]],
    mocker: MockerFixture,
) -> GrafanaAuthProvider:
    """Mock GrafanaSDK methods and pin Grafana as the active auth provider."""
    mocker.patch(
        "app.core.auth.config.get_active_auth_provider",
        return_value=grafana_provider,
    )
    mocker.patch(
        "app.core.auth.providers.grafana.sdk.GrafanaSDK.login",
        new=mocker.AsyncMock(return_value="grafana-session"),
    )
    mocker.patch(
        "app.core.auth.providers.grafana.sdk.GrafanaSDK.get_current_user",
        new=mocker.AsyncMock(return_value=grafana_user_record),
    )
    mocker.patch(
        "app.core.auth.providers.grafana.sdk.GrafanaSDK.get_current_user_orgs",
        new=mocker.AsyncMock(return_value=grafana_user_orgs),
    )
    mocker.patch(
        "app.core.auth.providers.grafana.sdk.GrafanaSDK.get_org_users",
        new=mocker.AsyncMock(return_value=grafana_org_users),
    )
    mocker.patch(
        "app.core.auth.providers.grafana.sdk.GrafanaSDK.lookup_user",
        new=mocker.AsyncMock(return_value=grafana_user_record),
    )
    return grafana_provider


@pytest.fixture
def admin_user(valid_username: str, faker: Faker) -> CasdoorUser:
    """Create a mock admin user with active status."""
    return CasdoorUserFactory.build(is_admin=True)


@pytest.fixture
def regular_user(valid_username: str, faker: Faker) -> CasdoorUser:
    """Create a mock regular user with active status."""
    return CasdoorUserFactory.build(
        username=valid_username,
        is_admin=False,
    )


@pytest.fixture
def created_node() -> CreatedNode:
    """Return a fake created node."""
    return CreatedNodeFactory.build(address="localhost")


@pytest.fixture
def created_service(created_node: CreatedNode) -> CreatedService:
    """Return a fake created service."""
    return CreatedServiceFactory.build(node=created_node, type=ServiceTypeEnum.MYSQL)


@pytest.fixture
def created_schema() -> CreatedSchema:
    """Return a fake created Schema."""
    return CreatedSchemaFactory.build()


@pytest.fixture
def created_table() -> CreatedTable:
    """Return a fake created Table."""
    return CreatedTableFactory.build()


@pytest.fixture
def mock_remote_api() -> AsyncMock:
    """Mock a RemoteAPI object."""
    return AsyncMock(spec=RemoteAPI)


POSTGRES_DSN_ENV = "SEP_TEST_POSTGRES_DSN"


def postgres_worker_schema() -> str:
    """Return the per-xdist-worker schema name for real-PostgreSQL tests.

    Each xdist worker gets its own schema so parallel workers never collide on
    ``CREATE``/``DROP`` against a shared database.
    """
    return f"sep_test_{os.environ.get('PYTEST_XDIST_WORKER', 'main')}"


@pytest_asyncio.fixture
async def postgres_engine() -> AsyncEngine:
    """Provide a real-PostgreSQL ``AsyncEngine`` for dialect-specific SQL tests.

    Connect through the already-present ``asyncpg`` driver to the DSN in
    ``$SEP_TEST_POSTGRES_DSN``. This is chosen over ``pytest-postgresql`` or
    ``testcontainers`` because it adds no dependency and the CI
    ``services: postgres`` container supplies the server. An unset env var skips
    the test (local runs without PostgreSQL); a set env var must connect, so a
    misconfigured CI service fails loudly instead of silently skipping — the
    connect is deliberately not wrapped in a try/skip.

    Function-scoped to match every other async fixture in the suite: the
    session-default event-loop scope makes a session-scoped async fixture bind to
    the wrong loop. Parallel-safe by construction — each xdist worker gets its own
    schema via ``schema_translate_map``, so reuse under xdist needs no serial-run
    convention.

    Pair with ``postgres_session`` for a real-PG-bound ``AsyncSession`` — the
    reusable seam for any code that dispatches on a real PostgreSQL bind.
    """
    dsn = os.environ.get(POSTGRES_DSN_ENV)
    if not dsn:
        pytest.skip(f"{POSTGRES_DSN_ENV} not set; skipping real-PostgreSQL tests")
    schema = postgres_worker_schema()
    base = create_async_engine(dsn, json_serializer=json_serializer)
    try:
        async with base.begin() as conn:
            await conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        yield base.execution_options(schema_translate_map={None: schema})
    finally:
        try:
            async with base.begin() as conn:
                await conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            await base.dispose()


@pytest_asyncio.fixture
async def postgres_session(postgres_engine: AsyncEngine) -> AsyncSession:
    """Provide a real-PostgreSQL ``AsyncSession`` with the tasks-service tables.

    Create every ``SQLModel`` table (including ``TaskHistory`` with its ``jsonb``
    ``execution_request``) in the worker schema, yield a session, then drop the
    tables on teardown. This is the seam reused by the ``func_json_extract``
    AutoJSON cell and by any test whose subject dispatches on the session bind.
    """
    async with postgres_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(postgres_engine)
    try:
        async with async_session_maker() as session:
            yield session
    finally:
        async with postgres_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)


MYSQL_DSN_ENV = "SEP_TEST_MYSQL_DSN"

#: Tables whose DDL MySQL 8 rejects, excluded so the MySQL lane can still create the
#: rest. ``taskhistory_log_state.staging`` is a ``LargeBinary`` carrying a
#: non-expression ``server_default``, which MySQL refuses on a BLOB column (error
#: 1101) -- only the parenthesised ``DEFAULT ('')`` form is legal there. A table
#: added to this set must have a tracked follow-up; a *new* incompatible table is
#: meant to fail the lane loudly rather than be added here silently.
MYSQL_INCOMPATIBLE_TABLES = frozenset({"taskhistory_log_state"})


def mysql_worker_database() -> str:
    """Return the per-xdist-worker database name for real-MySQL tests.

    A MySQL "schema" is a database, so the per-worker schema of
    ``postgres_worker_schema`` becomes a per-worker database here;
    ``schema_translate_map`` maps onto it identically.
    """
    return f"sep_test_{os.environ.get('PYTEST_XDIST_WORKER', 'main')}"


@pytest_asyncio.fixture
async def mysql_engine() -> AsyncEngine:
    """Provide a real-MySQL ``AsyncEngine`` for dialect-specific SQL tests.

    Mirror :func:`postgres_engine`, including its skip contract: an unset env var
    skips (local runs without MySQL), while a set-but-unreachable DSN is left to
    raise so a misconfigured CI service fails loudly.

    The per-worker database is created through the base engine rather than the
    translate-mapped one, which would try to qualify ``CREATE DATABASE`` itself.
    """
    dsn = os.environ.get(MYSQL_DSN_ENV)
    if not dsn:
        pytest.skip(f"{MYSQL_DSN_ENV} not set; skipping real-MySQL tests")
    database = mysql_worker_database()
    base = create_async_engine(dsn, json_serializer=json_serializer)
    try:
        async with base.begin() as conn:
            await conn.exec_driver_sql(f"CREATE DATABASE IF NOT EXISTS `{database}`")
        yield base.execution_options(schema_translate_map={None: database})
    finally:
        try:
            async with base.begin() as conn:
                await conn.exec_driver_sql(f"DROP DATABASE IF EXISTS `{database}`")
        finally:
            await base.dispose()


@pytest_asyncio.fixture
async def mysql_session(mysql_engine: AsyncEngine) -> AsyncSession:
    """Provide a real-MySQL ``AsyncSession`` over the MySQL-creatable ``SQLModel`` tables.

    Mirror :func:`postgres_session`: create the tables in the worker database, yield
    a session, then drop them on teardown. Unlike the PostgreSQL fixture this skips
    ``MYSQL_INCOMPATIBLE_TABLES``, whose DDL MySQL rejects.
    """
    tables = [
        table
        for table in SQLModel.metadata.sorted_tables
        if table.name not in MYSQL_INCOMPATIBLE_TABLES
    ]
    async with mysql_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, tables=tables)
    async_session_maker = get_async_session_maker_from_engine(mysql_engine)
    try:
        async with async_session_maker() as session:
            yield session
    finally:
        async with mysql_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all, tables=tables)


# The client/session fixtures below live here — the always-loaded ancestor conftest —
# rather than in ``tests/app/sep/conftest.py`` so they resolve regardless of single-process
# collection order. ``tests/app/sep/conftest.py`` re-exports them for the sep
# subtree; nearer conftests (tasks, inventory, sep/apps/*) still shadow them as before.


@pytest_asyncio.fixture(name="session")
async def session_fixture() -> AsyncGenerator[AsyncSession, None]:
    """Create an async db session for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    try:
        async with async_session_maker() as session:
            yield session
    finally:
        # ``StaticPool`` keeps the aiosqlite connection (and its non-daemon
        # thread) alive until the engine is disposed; without this the thread
        # survives to interpreter exit and blocks ``threading._shutdown``.
        await engine.dispose()


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
    try:
        async with async_session_maker() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
def test_client(regular_user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Yield an authenticated cookie-auth TestClient for the SEP app.

    Overrides ``require_bearer_for_unsafe_methods`` so cookie-only JSON
    mutations under ``/api/apps/*`` are not blocked by the framework
    Bearer gate. App-local ``test_client`` overrides MUST
    mirror this override; see :func:`api_admin_client_no_bearer` for the
    negative-path fixture that leaves the gate intact.

    ``get_session`` is overridden to the in-memory ``session`` so the
    ``require_app_enabled`` route guard reads an isolated, empty ``appstate``
    table (no rows -> every app enabled) instead of a shared, order-dependent
    DB. Tests that exercise the disabled path override ``get_session`` again
    with a session that carries an ``enabled=False`` row.
    """
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def api_admin_client_no_bearer(admin_user: CasdoorUser) -> TestClient:
    """Yield a cookie-auth admin TestClient with the Bearer gate intact.

    Mirrors :func:`test_client` but deliberately leaves
    ``require_bearer_for_unsafe_methods`` un-overridden, so cookie-only
    JSON mutations to ``/api/apps/*`` are rejected by the framework
    Bearer gate. Use in tests that assert the 401 path.
    """
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
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
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user

    transport = ASGITransport(app=sep_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    sep_app.dependency_overrides = {}


@pytest.fixture
def dummy_request() -> Request:
    """Create a dummy Request for dependencies that take one."""
    scope = {"type": "http", "headers": [], "client": ("127.0.0.1", "80"), "path": "/"}
    return Request(scope)


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
