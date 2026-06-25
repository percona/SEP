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

"""Define tests for the shared ``/health`` router built by ``build_health_router``."""

from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine, create_async_engine
from sqlmodel.pool import StaticPool
from starlette import status

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.health import build_health_router


def _build_app(session_maker_factory: Callable[[], async_sessionmaker]) -> FastAPI:
    app = FastAPI()
    app.include_router(build_health_router(session_maker_factory))
    return app


async def _get_health(app: FastAPI) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    return response.status_code, response.json()


@pytest_asyncio.fixture(name="reachable_engine")
async def reachable_engine_fixture() -> AsyncIterator[AsyncEngine]:
    """Yield an in-memory SQLite engine for the reachable-database cases."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_health_ok_when_db_reachable(reachable_engine: AsyncEngine) -> None:
    """Test a successful ``SELECT 1`` yields 200 with an ``ok`` body."""
    app = _build_app(lambda: get_async_session_maker_from_engine(reachable_engine))

    status_code, body = await _get_health(app)

    assert status_code == status.HTTP_200_OK
    assert body == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_503_when_db_unreachable() -> None:
    """Return 503 when the database is unreachable.

    An engine at an unopenable path makes ``SELECT 1`` raise a real
    ``OperationalError``, which the route surfaces as 503 -- exercising the
    failure path with a genuine DB error rather than a mocked session.
    """
    engine = create_async_engine("sqlite+aiosqlite:////nonexistent/dir/health.db")
    try:
        app = _build_app(lambda: get_async_session_maker_from_engine(engine))

        status_code, body = await _get_health(app)

        assert status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert body == {"status": "unavailable"}
    finally:
        await engine.dispose()


def test_health_excluded_from_openapi() -> None:
    """Keep ``/health`` out of the generated OpenAPI document.

    It is registered with ``include_in_schema=False`` so it never enters the
    OpenAPI document the frontend codegen guard tracks.
    """
    app = _build_app(async_sessionmaker)

    assert "/health" not in app.openapi().get("paths", {})
