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

"""Test inventory CRUD manager database-layer behavior."""

from datetime import datetime, UTC

import pytest
from pytest_mock import MockerFixture
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPBadRequestException
from app.inventory.crud import (
    HostSystemObservationManager,
    NodeManager,
    RetiredInclusiveNodeManager,
    SchemaManager,
    ServiceManager,
    ServiceSystemObservationManager,
    TableManager,
)
from app.inventory.models import (
    HostSystemObservation,
    Node,
    Schema,
    Service,
    ServiceSystemObservation,
    Table,
)
from tests.app.factories import ServiceWriteFactory
from tests.app.inventory.conftest import retire_in_place


def test_schema_and_table_sortable_allowlists_include_parent_ids() -> None:
    """Expose parent FK sort keys so the inventory UI sortable columns stay valid."""
    assert "service_id" in SchemaManager.list_query_spec.sortable
    assert "schema_id" in TableManager.list_query_spec.sortable
    SchemaManager.list_query_spec.resolve_sort("service_id")
    TableManager.list_query_spec.resolve_sort("-schema_id")


class TestRetirementReadPolicy:
    """Test how the retirable managers scope their reads."""

    @pytest.mark.asyncio
    async def test_eager_loaded_collection_drops_retired_children(
        self, session: AsyncSession, node: Node, service: Service
    ) -> None:
        """Filter a retired child out of its active parent's loaded collection."""
        await retire_in_place(session, service)

        nodes = await NodeManager.list(session, select_related=[Node.services])
        assert [loaded.id for loaded in nodes] == [node.id]
        assert nodes[0].services == []

    @pytest.mark.asyncio
    async def test_eager_loaded_parent_is_not_scoped(
        self, session: AsyncSession, node: Node, service: Service
    ) -> None:
        """Keep a many-to-one parent loaded even once it is retired.

        Scoping a required relationship would turn it into ``None`` rather than
        filter it, breaking the response models that declare it non-optional.
        """
        await retire_in_place(session, node)

        services = await ServiceManager.list(session, select_related=[Service.node])
        assert [loaded.id for loaded in services] == [service.id]
        assert services[0].node.id == node.id

    @pytest.mark.asyncio
    async def test_retired_inclusive_manager_injects_nothing(
        self, session: AsyncSession, node: Node, service: Service
    ) -> None:
        """Return retired rows, nested ones included, through the sibling manager."""
        await retire_in_place(session, node)
        await retire_in_place(session, service)

        assert await NodeManager.list(session) == []
        nodes = await RetiredInclusiveNodeManager.list(
            session, select_related=[Node.services]
        )
        assert [loaded.id for loaded in nodes] == [node.id]
        assert [child.id for child in nodes[0].services] == [service.id]


class TestRetirementCascade:
    """Test the retire and revive cascades."""

    @pytest.mark.asyncio
    async def test_cascade_leaves_an_already_retired_descendant_alone(
        self,
        session: AsyncSession,
        node: Node,
        service: Service,
        schema: Schema,
        table: Table,
    ) -> None:
        """Keep the original timestamp of a row that was already retired."""
        await retire_in_place(session, schema, datetime(2020, 1, 1, tzinfo=UTC))
        already_retired_at = schema.retired_at

        await NodeManager.retire(session, node)

        await session.refresh(schema)
        await session.refresh(table)
        assert schema.retired_at == already_retired_at
        assert table.retired_at is not None
        assert table.retired_at != already_retired_at

    @pytest.mark.asyncio
    async def test_cascade_keeps_the_system_observations(
        self,
        session: AsyncSession,
        node: Node,
        service: Service,
        host_observation: HostSystemObservation,
        service_observation: ServiceSystemObservation,
    ) -> None:
        """Keep both observation rows, which a hard delete would have cascaded away."""
        await NodeManager.retire(session, node)

        assert (
            await HostSystemObservationManager.get(session, id=host_observation.id)
            is not None
        )
        assert (
            await ServiceSystemObservationManager.get(
                session, id=service_observation.id
            )
            is not None
        )

    @pytest.mark.asyncio
    async def test_cascade_persists_nothing_when_a_statement_fails(
        self,
        mocker: MockerFixture,
        session: AsyncSession,
        node: Node,
        service: Service,
        schema: Schema,
        table: Table,
    ) -> None:
        """Publish no part of the subtree when one statement of the cascade fails.

        The cascade issues its own statements and commits once, so a failure
        anywhere in it leaves the whole subtree active rather than half retired.
        """
        entity_ids = (node.id, service.id, schema.id, table.id)
        real_exec = session.exec

        async def exec_failing_on_node(statement: object, *args: object) -> object:
            target = getattr(statement, "table", None)
            if target is not None and target.name == Node.__tablename__:
                raise RuntimeError("cascade interrupted")
            return await real_exec(statement, *args)

        mocker.patch.object(session, "exec", side_effect=exec_failing_on_node)

        with pytest.raises(RuntimeError, match="cascade interrupted"):
            await NodeManager.retire(session, node)
        await session.rollback()

        managers = (NodeManager, ServiceManager, SchemaManager, TableManager)
        for manager, entity_id in zip(managers, entity_ids, strict=True):
            assert (await manager.get(session, id=entity_id)).retired_at is None


@pytest.mark.asyncio
async def test_dangling_fk_rejected_by_database(session: AsyncSession) -> None:
    """Reject a dangling parent FK at the database layer.

    ``create`` injects the FK from a path-validated parent and runs no parent
    pre-check, so this exercises the SQLite foreign-key constraint directly
    (``PRAGMA foreign_keys = ON`` is enabled on the inventory test engine). The
    DB ``IntegrityError`` surfaces as ``HTTPBadRequestException`` because
    ``BaseSQLModelManager.save`` translates database errors on commit.
    """
    with pytest.raises(HTTPBadRequestException):
        await ServiceManager.create(session, ServiceWriteFactory.build(), node_id=9999)
