# Copyright 2026 Percona LLC
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

"""Define test fixtures for tasks tests."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.pool import StaticPool
from starlette.testclient import TestClient

from app.api.deps import get_current_user
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.models import CasdoorUser
from app.tasks.db.utils import json_deserialize
from app.tasks.deps import get_session
from app.tasks.main import tasks_app


@pytest_asyncio.fixture(name="session")
async def session_fixture() -> AsyncSession:
    """Create an async db session for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        json_deserializer=json_deserialize,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    async with async_session_maker() as session:
        yield session


@pytest.fixture
def test_client(regular_user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Create an authenticated test client for the app."""
    tasks_app.dependency_overrides[get_current_user] = lambda: regular_user
    tasks_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(tasks_app)
    tasks_app.dependency_overrides = {}
