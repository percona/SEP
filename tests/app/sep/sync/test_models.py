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

"""Define tests for the app.sep.sync.model module."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.inventory.models import ServiceTypeEnum
from app.sep.crud import SyncInstanceManager
from app.sep.inventory import (
    CreatedNode,
    CreatedSchema,
    CreatedService,
    CreatedTable,
)
from app.sep.models import (
    SyncInstance,
    SyncInventoryEntityTypeEnum,
    SyncItem,
    SyncItemWrite,
)
from app.sep.sync.models import BaseSyncer, BaseTaskSyncer
from app.tasks.models import TaskHistoryStatusEnum
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
    MOCK_CREATED_NODE_ID,
)


@pytest.fixture
def mock_sync_items(mock_remote_api, mocker) -> dict[tuple[int, None], SyncItem]:
    """Mock SyncItem and context manager for BaseSyncer."""
    mock_sync_item = AsyncMock(spec=SyncItem)
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_sync_item
    mock_context_manager.__aexit__.return_value = None
    mocker.patch(
        "app.sep.sync.models.BaseSyncer.manage_sync_item",
        return_value=mock_context_manager,
    )
    return {
        (SyncInventoryEntityTypeEnum.INVENTORY, None): mock_sync_item,
    }


@pytest.fixture
def created_node() -> CreatedNode:
    """Return a fake created node."""
    created_node = CreatedNodeFactory.build()
    created_node.id = MOCK_CREATED_NODE_ID
    created_node.address = "localhost"
    return created_node


@pytest.fixture
def created_service(created_node) -> CreatedService:
    """Return a fake created service."""
    created_service = CreatedServiceFactory.build()
    created_service.type = ServiceTypeEnum.MYSQL
    created_service.environment = None
    return created_service


@pytest.fixture
def created_schema(created_service) -> CreatedSchema:
    """Return a fake created Schema."""
    created_schema = CreatedSchemaFactory.build()
    created_schema.service = created_service
    return created_schema


@pytest.fixture
def created_table(created_schema) -> CreatedTable:
    """Return a fake created Table."""
    created_table = CreatedTableFactory.build()
    created_table.database = created_schema
    return created_table


@pytest.mark.asyncio
async def test_aenter_initializes_session(mock_remote_api, mocker):
    """Test session init and closure with __aenter__ and __aexit__."""
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    mock_session.exec = AsyncMock()

    mock_session_maker = MagicMock(return_value=mock_session)

    mock_finish_hanging_items = AsyncMock()
    mocker.patch(
        "app.sep.sync.models.SyncInstanceManager.finish_hanging_items",
        mock_finish_hanging_items,
    )

    mock_create_sync_instance = AsyncMock()
    mocker.patch(
        "app.sep.sync.models.get_async_session_maker", return_value=mock_session_maker
    )
    with patch.object(SyncInstanceManager, "create", mock_create_sync_instance):

        class TestSyncer(BaseSyncer):
            SYNC_TO_LIMIT = MagicMock()

        syncer = TestSyncer(
            inventory_api=mock_remote_api,
            sync_instance=None,
        )
        async with syncer as result:
            mock_session_maker.assert_called_once()
            mock_session.__aenter__.assert_called_once()

        assert result.sync_instance == mock_create_sync_instance.return_value

        mock_finish_hanging_items.assert_awaited_once_with(
            mock_session,
            syncer.sync_instance.id,
        )


@pytest.mark.asyncio
async def test_prepare_sync(created_node, mock_remote_api, mocker):
    """Test preparing synchronization for a given entity and its children."""
    expected_call_count = 2

    class TestSyncer(BaseSyncer):
        SYNC_TO_LIMIT = SyncInventoryEntityTypeEnum.NODE

    syncer = TestSyncer(
        inventory_api=mock_remote_api, sync_instance=None, _session=AsyncMock()
    )
    mock_sync_item = AsyncMock(spec=SyncItem)
    mock_get_sync_item = mocker.patch(
        "app.sep.sync.models.BaseSyncer.get_sync_item",
        new_callable=AsyncMock,
    )
    mock_get_sync_item.side_effect = [mock_sync_item, mock_sync_item]
    mock_remote_api.get.side_effect = [
        {"items": [created_node.model_dump()], "total": 1, "offset": 0, "limit": 50},
    ]

    await syncer.prepare_sync(SyncInventoryEntityTypeEnum.INVENTORY, None)

    assert mock_get_sync_item.call_count == expected_call_count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entity_type",
    [
        (SyncInventoryEntityTypeEnum.SERVICE),
        (SyncInventoryEntityTypeEnum.INVENTORY),
        (SyncInventoryEntityTypeEnum.NODE),
    ],
)
async def test_get_children_entities(entity_type, mock_remote_api, created_service):
    """Test retrieving child entities for a given entity type and entity."""
    created_entity = None
    syncer = BaseSyncer(
        inventory_api=mock_remote_api, sync_instance=None, _session=AsyncMock()
    )
    if entity_type == SyncInventoryEntityTypeEnum.SERVICE:
        created_entity = created_service
        mock_remote_api.get.side_effect = [created_service.model_dump()]
    await syncer.get_children_entities(entity_type, created_entity)


@pytest.mark.asyncio
async def test_get_sync_items(mock_remote_api, mocker):
    """Test retrieving multiple SyncItems for specified entities."""
    mock_sync_instance = AsyncMock(spec=SyncInstance)
    mock_sync_instance.id = uuid.uuid4()
    mock_sync_item_write = AsyncMock(spec=SyncItemWrite)

    class TestSyncer(BaseSyncer):
        _session = AsyncMock(spec=AsyncSession)

    syncer = TestSyncer(
        inventory_api=mock_remote_api,
        sync_instance=mock_sync_instance,
    )
    mock_get_or_create = mocker.patch(
        "app.sep.sync.models.SyncItemManager.get_or_create",
        new_callable=AsyncMock,
    )
    mock_get_or_create.side_effect = [
        (mock_sync_item_write, True),
    ]
    await syncer.get_sync_items(SyncInventoryEntityTypeEnum.INVENTORY, None)


@pytest.mark.asyncio
async def test_manage_sync_item(mock_remote_api, mocker):
    """Test managing the synchronization lifecycle of a SyncItem."""
    mock_sync_instance = AsyncMock(spec=SyncInstance)
    mock_sync_instance.id = uuid.uuid4()
    mock_sync_item = AsyncMock(spec=SyncItem)
    mock_sync_items = {
        (SyncInventoryEntityTypeEnum.INVENTORY, None): mock_sync_item,
    }

    class TestSyncer(BaseSyncer):
        _session = (AsyncMock(spec=AsyncSession),)

    syncer = TestSyncer(
        inventory_api=mock_remote_api,
        sync_instance=mock_sync_instance,
        sync_items=mock_sync_items,
    )
    mock_prepare_sync = mocker.patch(
        "app.sep.sync.models.BaseSyncer.prepare_sync",
        new_callable=AsyncMock,
    )
    mock_start_sync = mocker.patch(
        "app.sep.sync.models.SyncItemManager.start_sync", new_callable=AsyncMock
    )
    mock_finish_sync = mocker.patch(
        "app.sep.sync.models.BaseSyncer.finish_sync", new_callable=AsyncMock
    )
    async with syncer.manage_sync_item(SyncInventoryEntityTypeEnum.INVENTORY, None):
        pass
    assert mock_prepare_sync.call_count == 0
    assert mock_start_sync.call_count == 1
    assert mock_finish_sync.call_count == 1


@pytest.mark.asyncio
async def test_finsih_sync(mock_remote_api, mocker):
    """Test finalizing synchronization for a given entity and its children."""
    mock_sync_item = AsyncMock(spec=SyncItem)
    mock_sync_items = {
        (SyncInventoryEntityTypeEnum.INVENTORY, None): mock_sync_item,
    }

    class TestSyncer(BaseSyncer):
        _session = (AsyncMock(spec=AsyncSession),)

    syncer = TestSyncer(
        inventory_api=mock_remote_api,
        sync_instance=None,
        sync_items=mock_sync_items,
    )
    mock_finish_sync = mocker.patch(
        "app.sep.sync.models.SyncItemManager.finish_sync", new_callable=AsyncMock
    )
    await syncer.finish_sync(SyncInventoryEntityTypeEnum.INVENTORY, None)

    assert mock_finish_sync.call_count == 1


@pytest.mark.asyncio
async def test_delete_node(
    created_node,
    created_service,
    created_schema,
    created_table,
    mock_remote_api,
    mocker,
):
    """Test deleting inventories from the inventory system."""
    mock_sync_item = AsyncMock(spec=SyncItem)
    mock_sync_items = {
        (SyncInventoryEntityTypeEnum.INVENTORY, None): mock_sync_item,
    }

    class TestSyncer(BaseSyncer):
        _session = (AsyncMock(spec=AsyncSession),)
        SYNC_TO_LIMIT = SyncInventoryEntityTypeEnum.NODE

    syncer = TestSyncer(
        inventory_api=mock_remote_api,
        sync_instance=None,
        sync_items=mock_sync_items,
    )

    mock_remote_api.delete.side_effect = [
        created_node.model_dump(),
        created_service.model_dump(),
        created_schema.model_dump(),
        created_table.model_dump(),
    ]

    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_sync_item
    mock_context_manager.__aexit__.return_value = None
    mocker.patch(
        "app.sep.sync.models.BaseSyncer.manage_sync_item",
        return_value=mock_context_manager,
    )
    await syncer.delete_node(created_node)
    mock_remote_api.delete.assert_awaited_once_with(f"/{created_node.id}")
    mock_remote_api.delete.reset_mock()
    await syncer.delete_service(created_service)
    mock_remote_api.delete.assert_awaited_once_with(f"/services/{created_service.id}")
    mock_remote_api.delete.reset_mock()
    await syncer.delete_schema(created_schema)
    mock_remote_api.delete.assert_awaited_once_with(f"/schemas/{created_schema.id}")
    mock_remote_api.delete.reset_mock()
    await syncer.delete_table(created_table)
    mock_remote_api.delete.assert_awaited_once_with(f"/tables/{created_table.id}")


@pytest.mark.asyncio
async def test_sync_inventory(mock_remote_api, mock_sync_items, mocker):
    """Test synchronizating the entire inventory."""

    class TestSyncer(BaseSyncer):
        SYNC_TO_LIMIT = SyncInventoryEntityTypeEnum.NODE
        _session = (AsyncMock(spec=AsyncSession),)

    syncer = TestSyncer(
        inventory_api=mock_remote_api,
        sync_instance=None,
        sync_items=mock_sync_items,
    )

    mock_perform_inventory_sync = mocker.patch(
        "app.sep.sync.models.BaseSyncer.perform_inventory_sync",
        new_callable=AsyncMock,
    )
    await syncer.sync_inventory()
    mock_perform_inventory_sync.assert_called_once()


@pytest.mark.asyncio
async def test_sync_node(created_node, mock_remote_api, mock_sync_items, mocker):
    """Test synchronizing data for a specific node."""

    class TestSyncer(BaseSyncer):
        SYNC_TO_LIMIT = SyncInventoryEntityTypeEnum.NODE
        _session = (AsyncMock(spec=AsyncSession),)

    syncer = TestSyncer(
        inventory_api=mock_remote_api,
        sync_instance=None,
        sync_items=mock_sync_items,
    )

    mock_perform_node_sync = mocker.patch(
        "app.sep.sync.models.BaseSyncer.perform_node_sync",
        new_callable=AsyncMock,
    )
    mock_fetch_node = mocker.patch(
        "app.sep.sync.models.BaseSyncer.fetch_node",
        new_callable=AsyncMock,
    )
    await syncer.sync_node(created_node, None)
    mock_perform_node_sync.assert_called_once()
    mock_fetch_node.assert_called_once()


@pytest.mark.asyncio
async def test_sync_node_skips_when_fetch_returns_none(
    created_node, mock_remote_api, mock_sync_items, mocker
):
    """Test sync_node skips synchronization when fetch_node returns None."""

    class TestSyncer(BaseSyncer):
        SYNC_TO_LIMIT = SyncInventoryEntityTypeEnum.NODE
        _session = (AsyncMock(spec=AsyncSession),)

    syncer = TestSyncer(
        inventory_api=mock_remote_api,
        sync_instance=None,
        sync_items=mock_sync_items,
    )

    mock_perform_node_sync = mocker.patch(
        "app.sep.sync.models.BaseSyncer.perform_node_sync",
        new_callable=AsyncMock,
    )
    mocker.patch(
        "app.sep.sync.models.BaseSyncer.fetch_node",
        new_callable=AsyncMock,
        return_value=None,
    )
    await syncer.sync_node(created_node, None)
    mock_perform_node_sync.assert_not_called()


@pytest.mark.asyncio
async def test_sync_service(created_service, mock_remote_api, mock_sync_items, mocker):
    """Test synchronizing data for a specific service."""

    class TestSyncer(BaseSyncer):
        SYNC_TO_LIMIT = SyncInventoryEntityTypeEnum.SERVICE
        _session = (AsyncMock(spec=AsyncSession),)

    syncer = TestSyncer(
        inventory_api=mock_remote_api,
        sync_instance=None,
        sync_items=mock_sync_items,
    )

    mock_perform_service_sync = mocker.patch(
        "app.sep.sync.models.BaseSyncer.perform_service_sync",
        new_callable=AsyncMock,
    )
    mock_fetch_service = mocker.patch(
        "app.sep.sync.models.BaseSyncer.fetch_service",
        new_callable=AsyncMock,
    )
    await syncer.sync_service(created_service, None)
    mock_perform_service_sync.assert_called_once()
    mock_fetch_service.assert_called_once()


@pytest.mark.asyncio
async def test_sync_service_skips_when_fetch_returns_none(
    created_service, mock_remote_api, mock_sync_items, mocker
):
    """Test sync_service skips synchronization when fetch_service returns None."""

    class TestSyncer(BaseSyncer):
        SYNC_TO_LIMIT = SyncInventoryEntityTypeEnum.SERVICE
        _session = (AsyncMock(spec=AsyncSession),)

    syncer = TestSyncer(
        inventory_api=mock_remote_api,
        sync_instance=None,
        sync_items=mock_sync_items,
    )

    mock_perform_service_sync = mocker.patch(
        "app.sep.sync.models.BaseSyncer.perform_service_sync",
        new_callable=AsyncMock,
    )
    mocker.patch(
        "app.sep.sync.models.BaseSyncer.fetch_service",
        new_callable=AsyncMock,
        return_value=None,
    )
    await syncer.sync_service(created_service, None)
    mock_perform_service_sync.assert_not_called()


@pytest.mark.asyncio
async def test_sync_schema(created_schema, mock_remote_api, mock_sync_items, mocker):
    """Test synchronizing data for a specific schema."""

    class TestSyncer(BaseSyncer):
        SYNC_TO_LIMIT = SyncInventoryEntityTypeEnum.SCHEMA
        _session = (AsyncMock(spec=AsyncSession),)

    syncer = TestSyncer(
        inventory_api=mock_remote_api,
        sync_instance=None,
        sync_items=mock_sync_items,
    )

    mock_perform_schema_sync = mocker.patch(
        "app.sep.sync.models.BaseSyncer.perform_schema_sync",
        new_callable=AsyncMock,
    )
    mock_fetch_schema = mocker.patch(
        "app.sep.sync.models.BaseSyncer.fetch_schema",
        new_callable=AsyncMock,
    )
    await syncer.sync_schema(created_schema, None)
    mock_perform_schema_sync.assert_called_once()
    mock_fetch_schema.assert_called_once()


@pytest.mark.asyncio
async def test_sync_table(created_table, mock_remote_api, mock_sync_items, mocker):
    """Test synchronizing data for a specific table."""

    class TestSyncer(BaseSyncer):
        SYNC_TO_LIMIT = SyncInventoryEntityTypeEnum.TABLE
        _session = (AsyncMock(spec=AsyncSession),)

    syncer = TestSyncer(
        inventory_api=mock_remote_api,
        sync_instance=None,
        sync_items=mock_sync_items,
    )

    mock_perform_table_sync = mocker.patch(
        "app.sep.sync.models.BaseSyncer.perform_table_sync",
        new_callable=AsyncMock,
    )
    mock_fetch_table = mocker.patch(
        "app.sep.sync.models.BaseSyncer.fetch_table",
        new_callable=AsyncMock,
    )
    await syncer.sync_table(created_table, None)
    mock_perform_table_sync.assert_called_once()
    mock_fetch_table.assert_called_once()


@pytest.mark.asyncio
async def test_update_table(created_table, mock_remote_api):
    """Test updating a table in the inventory system."""
    updated_table = created_table.model_copy(
        update={"create": "UPDATED CREATE STATEMENT"}
    )
    syncer = BaseSyncer(
        inventory_api=mock_remote_api, sync_instance=None, _session=AsyncMock()
    )
    mock_remote_api.put.side_effect = [updated_table.model_dump()]
    await syncer.update_table(created_table, updated_table)
    mock_remote_api.put.assert_awaited_once_with(
        f"/tables/{created_table.id}", json=updated_table.model_dump()
    )


@pytest.mark.asyncio
async def test_wait_for_task_output(mock_remote_api):
    """Test waiting for a task to complete and retrieve its output."""
    step_name = "mock_step_name"
    expected_call_count = 2
    mock_remote_api.post.side_effect = [
        {
            "id": "12345",
            "status": TaskHistoryStatusEnum.PENDING,
        }
    ]

    mock_remote_api.get.side_effect = [
        {"id": "12345", "status": TaskHistoryStatusEnum.RUNNING},
        {
            "id": "12345",
            "status": TaskHistoryStatusEnum.SUCCESS,
            "execution_request": {
                "tracking": {
                    "task_logs": {
                        step_name: {
                            "stdout": "Task completed successfully.",
                            "stderr": "",
                        }
                    }
                }
            },
        },
    ]

    class TestTaskSyncer(BaseTaskSyncer):
        _session = (AsyncMock(spec=AsyncSession),)

    task_syncer = TestTaskSyncer(
        inventory_api=mock_remote_api,
        tasks_api=mock_remote_api,
        sync_instance=None,
        tasks_execution_wait_interval=0,
    )

    await task_syncer.wait_for_task_output(task_name="syncing", stdout_step=step_name)

    mock_remote_api.post.assert_awaited_once()
    assert mock_remote_api.get.await_count == expected_call_count
