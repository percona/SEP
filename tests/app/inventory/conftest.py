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

"""Define test fixtures for inventory tests."""

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
from app.inventory.crud import NodeManager, SchemaManager, ServiceManager, TableManager
from app.inventory.deps import get_session
from app.inventory.main import inventory_app
from app.inventory.models import Node, Schema, Service, Table
from app.models import CasdoorUser
from tests.app.factories import (
    NodeWriteFactory,
    SchemaWriteFactory,
    ServiceWriteFactory,
    TableWriteFactory,
)


@pytest_asyncio.fixture(name="session")
async def session_fixture() -> AsyncSession:
    """Create an async database session for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    async with async_session_maker() as session:
        yield session


@pytest.fixture
def test_client(regular_user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Create an authenticated test client for the inventory app."""
    inventory_app.dependency_overrides[get_current_user] = lambda: regular_user
    inventory_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(inventory_app)
    inventory_app.dependency_overrides = {}


@pytest_asyncio.fixture
async def node(session: AsyncSession) -> Node:
    """Create a node in the database."""
    return await NodeManager.create(session, NodeWriteFactory.build())


@pytest_asyncio.fixture
async def service(session: AsyncSession, node: Node) -> Service:
    """Create a service in the database."""
    return await ServiceManager.create(
        session, ServiceWriteFactory.build(), node_id=node.id
    )


@pytest_asyncio.fixture
async def schema(session: AsyncSession, service: Service) -> Schema:
    """Create a schema in the database."""
    return await SchemaManager.create(
        session, SchemaWriteFactory.build(), service_id=service.id
    )


@pytest_asyncio.fixture
async def table(session: AsyncSession, schema: Schema) -> Table:
    """Create a table in the database."""
    return await TableManager.create(
        session, TableWriteFactory.build(), schema_id=schema.id
    )


@pytest_asyncio.fixture
async def second_table(session: AsyncSession, schema: Schema, table: Table) -> Table:
    """Create a second table in the database (name must differ per ``ix_table_name_schema_id``)."""
    data = TableWriteFactory.build()
    return await TableManager.create(
        session,
        data.model_copy(update={"name": f"second_table_{table.id}"}),
        schema_id=schema.id,
    )
