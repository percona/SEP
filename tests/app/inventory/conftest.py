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

import sqlite3
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.pool import StaticPool
from starlette.testclient import TestClient

from app.api.deps import get_current_user, require_minimum_role_for_unsafe_methods
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.core.utils.date_time import utc_now
from app.inventory.crud import (
    HostSystemObservationManager,
    NodeManager,
    SchemaManager,
    ServiceManager,
    ServiceSystemObservationManager,
    TableManager,
)
from app.inventory.deps import get_session
from app.inventory.main import inventory_app
from app.inventory.models import (
    HostSystemObservation,
    Node,
    RetirableSQLModel,
    Schema,
    Service,
    ServiceSystemObservation,
    Table,
)
from tests.app.factories import (
    HostSystemObservationWriteFactory,
    NodeWriteFactory,
    SchemaWriteFactory,
    ServiceSystemObservationWriteFactory,
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

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(
        dbapi_connection: sqlite3.Connection,
        _connection_record: object,
    ) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    try:
        async with async_session_maker() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
def test_client(regular_user: CasdoorUser, session: AsyncSession) -> TestClient:
    """Create an authenticated test client for the inventory app.

    Mirrors the SEP ``test_client``'s ``require_minimum_role_for_unsafe_methods``
    override so the non-admin fixture user can exercise a mutating route.
    """
    inventory_app.dependency_overrides[require_minimum_role_for_unsafe_methods] = (
        lambda: None
    )
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
        session,
        TableWriteFactory.build(name="inventory_test_table_one"),
        schema_id=schema.id,
    )


@pytest_asyncio.fixture
async def second_table(session: AsyncSession, schema: Schema, table: Table) -> Table:
    """Create a second table in the database (name must differ per ``ix_table_name_schema_id``)."""
    return await TableManager.create(
        session,
        TableWriteFactory.build(name="inventory_test_table_two"),
        schema_id=schema.id,
    )


async def retire_in_place(
    session: AsyncSession,
    instance: RetirableSQLModel,
    retired_at: datetime | None = None,
) -> None:
    """Retire a single row without cascading, bypassing the retire route.

    Read-policy tests need a tombstone that the code under test did not create,
    and several need one whose ancestors stay active.

    :param session: The async database session owning the instance.
    :param instance: The row to mark retired.
    :param retired_at: The timestamp to stamp, defaulting to now. Pass a distinctly
        older one to tell a pre-existing tombstone apart from a fresh cascade,
        which SQLite's second-resolution timestamps otherwise merge.
    """
    instance.retired_at = retired_at or utc_now()
    instance.retirement_key = instance.id
    session.add(instance)
    await session.commit()
    await session.refresh(instance)


@pytest_asyncio.fixture
async def retired_node(session: AsyncSession, node: Node) -> Node:
    """Retire the node, leaving its subtree active."""
    await retire_in_place(session, node)
    return node


@pytest_asyncio.fixture
async def retired_service(session: AsyncSession, service: Service) -> Service:
    """Retire the service, leaving its node and subtree active."""
    await retire_in_place(session, service)
    return service


@pytest_asyncio.fixture
async def retired_schema(session: AsyncSession, schema: Schema) -> Schema:
    """Retire the schema, leaving its ancestors and tables active."""
    await retire_in_place(session, schema)
    return schema


@pytest_asyncio.fixture
async def retired_table(session: AsyncSession, table: Table) -> Table:
    """Retire the table, leaving its ancestors active."""
    await retire_in_place(session, table)
    return table


@pytest_asyncio.fixture
async def host_observation(session: AsyncSession, node: Node) -> HostSystemObservation:
    """Create a host system observation for the node."""
    return await HostSystemObservationManager.create(
        session,
        HostSystemObservationWriteFactory.build(),
        node_id=node.id,
    )


@pytest_asyncio.fixture
async def service_observation(
    session: AsyncSession, service: Service
) -> ServiceSystemObservation:
    """Create a service system observation for the service."""
    return await ServiceSystemObservationManager.create(
        session,
        ServiceSystemObservationWriteFactory.build(),
        service_id=service.id,
    )
