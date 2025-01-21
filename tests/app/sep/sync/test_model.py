"""Define tests for the app.sep.sync.model module."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.requests import RemoteAPI
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
from app.sep.sync.models import BaseSyncer
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
    MOCK_CREATED_NODE_ID,
)


@pytest.fixture
def mock_inventory_api() -> AsyncMock:
    """Mock the InventoryAPI dependency."""
    return AsyncMock(spec=RemoteAPI)


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
async def test_aenter_initializes_session(mock_inventory_api, mocker):
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
            inventory_api=mock_inventory_api,
            sync_instance=None,
            _session=None,
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
async def test_prepare_sync(created_node, mock_inventory_api, mocker):
    """Test preparing synchronization for a given entity and its children."""
    expected_call_count = 2

    class TestSyncer(BaseSyncer):
        SYNC_TO_LIMIT = SyncInventoryEntityTypeEnum.NODE

    syncer = TestSyncer(
        inventory_api=mock_inventory_api, sync_instance=None, _session=AsyncMock()
    )
    mock_sync_item = AsyncMock(spec=SyncItem)
    mock_get_sync_item = mocker.patch(
        "app.sep.sync.models.BaseSyncer.get_sync_item",
        new_callable=AsyncMock,
    )
    mock_get_sync_item.side_effect = [mock_sync_item, mock_sync_item]
    mock_inventory_api.get.side_effect = [[created_node.model_dump()]]

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
async def test_get_children_entities(entity_type, mock_inventory_api, created_service):
    """Test retrieving child entities for a given entity type and entity."""
    created_entity = None
    syncer = BaseSyncer(
        inventory_api=mock_inventory_api, sync_instance=None, _session=AsyncMock()
    )
    if entity_type == SyncInventoryEntityTypeEnum.SERVICE:
        created_entity = created_service
        mock_inventory_api.get.side_effect = [created_service.model_dump()]
    await syncer.get_children_entities(entity_type, created_entity)


@pytest.mark.asyncio
async def test_get_sync_items(mock_inventory_api, mocker):
    """Test retrieving multiple SyncItems for specified entities."""
    mock_sync_instance = AsyncMock(spec=SyncInstance)
    mock_sync_instance.id = uuid.uuid4()
    mock_sync_item_write = AsyncMock(spec=SyncItemWrite)

    class TestSyncer(BaseSyncer):
        _session = AsyncMock(spec=AsyncSession)

    syncer = TestSyncer(
        inventory_api=mock_inventory_api,
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
async def test_manage_sync_item(mock_inventory_api, mocker):
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
        inventory_api=mock_inventory_api,
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
async def test_finsih_sync(mock_inventory_api, mocker):
    """Test finalizing synchronization for a given entity and its children."""
    mock_sync_item = AsyncMock(spec=SyncItem)
    mock_sync_items = {
        (SyncInventoryEntityTypeEnum.INVENTORY, None): mock_sync_item,
    }

    class TestSyncer(BaseSyncer):
        _session = (AsyncMock(spec=AsyncSession),)

    syncer = TestSyncer(
        inventory_api=mock_inventory_api,
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
    mock_inventory_api,
    mocker,
):
    """Test deleting inventories from the inventory system."""
    mock_sync_item = AsyncMock(spec=SyncItem)
    mock_sync_items = {
        (SyncInventoryEntityTypeEnum.INVENTORY, None): mock_sync_item,
    }

    class TestSyncer(BaseSyncer):
        _session = (AsyncMock(spec=AsyncSession),)

    syncer = TestSyncer(
        inventory_api=mock_inventory_api,
        sync_instance=None,
        sync_items=mock_sync_items,
    )

    mock_inventory_api.delete.side_effect = [
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
    mock_inventory_api.delete.assert_awaited_once_with(f"/{created_node.id}")
    mock_inventory_api.delete.reset_mock()
    await syncer.delete_service(created_service)
    mock_inventory_api.delete.assert_awaited_once_with(
        f"/services/{created_service.id}"
    )
    mock_inventory_api.delete.reset_mock()
    await syncer.delete_schema(created_schema)
    mock_inventory_api.delete.assert_awaited_once_with(f"/schemas/{created_schema.id}")
    mock_inventory_api.delete.reset_mock()
    await syncer.delete_table(created_table)
    mock_inventory_api.delete.assert_awaited_once_with(f"/tables/{created_table.id}")
