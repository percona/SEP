"""Define tests for the app.sep.plugins.inventory.sync module."""

from unittest.mock import AsyncMock

import pytest

from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.plugins.inventory.sync import (
    run_inventory_sync,
    run_node_sync,
    run_schema_sync,
    run_service_sync,
    run_table_sync,
)
from app.sep.sync.models import BaseSyncer
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
)


@pytest.fixture
def mock_base_syncer_factory():
    """Create a new mock BaseSyncer instance."""

    def _create_mock_syncer():
        mock_syncer = AsyncMock(BaseSyncer)
        mock_syncer.__aenter__.return_value = mock_syncer
        mock_syncer.__aexit__.return_value = None
        return mock_syncer

    return _create_mock_syncer


@pytest.fixture
def created_node() -> CreatedNode:
    """Return a fake created node."""
    return CreatedNodeFactory.build()


@pytest.fixture
def created_service(created_node) -> CreatedService:
    """Return a fake created service."""
    created_service = CreatedServiceFactory.build()
    created_service.node = created_node
    return created_service


@pytest.fixture
def created_schema(created_service) -> CreatedSchema:
    """Return a fake created Schema."""
    created_schema = CreatedSchemaFactory.build()
    created_schema.service = created_service
    return created_schema


@pytest.fixture
def created_table() -> CreatedTable:
    """Return a fake created Table."""
    return CreatedTableFactory.build()


@pytest.mark.asyncio
async def test_run_inventory_sync(mock_base_syncer_factory):
    """Test executing inventory synchronization using the provided syncers."""
    syncer1 = mock_base_syncer_factory()
    syncer2 = mock_base_syncer_factory()

    await run_inventory_sync(syncer1, syncer2)

    syncer1.sync_inventory.assert_awaited_once()
    syncer2.sync_inventory.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_node_sync(created_node, mock_base_syncer_factory):
    """Test executing node synchronization for a created node."""
    syncer1 = mock_base_syncer_factory()
    syncer2 = mock_base_syncer_factory()

    await run_node_sync(created_node, syncer1, syncer2)

    syncer1.sync_node.assert_awaited_once_with(created_node, refresh_at_start=False)
    syncer2.sync_node.assert_awaited_once_with(created_node, refresh_at_start=True)


@pytest.mark.asyncio
async def test_run_service_sync(created_service, mock_base_syncer_factory):
    """Test executing service synchronization for a created service."""
    syncer1 = mock_base_syncer_factory()
    syncer2 = mock_base_syncer_factory()

    await run_service_sync(created_service, syncer1, syncer2)

    syncer1.sync_service.assert_awaited_once_with(
        created_service, refresh_at_start=False
    )
    syncer2.sync_service.assert_awaited_once_with(
        created_service, refresh_at_start=True
    )


@pytest.mark.asyncio
async def test_run_schema_sync(created_schema, mock_base_syncer_factory):
    """Test executing schema synchronization for a created schema."""
    syncer1 = mock_base_syncer_factory()
    syncer2 = mock_base_syncer_factory()

    await run_schema_sync(created_schema, syncer1, syncer2)

    syncer1.sync_schema.assert_awaited_once_with(created_schema, refresh_at_start=False)
    syncer2.sync_schema.assert_awaited_once_with(created_schema, refresh_at_start=True)


@pytest.mark.asyncio
async def test_run_table_sync(created_table, mock_base_syncer_factory):
    """Test executing table synchronization for a created table."""
    syncer1 = mock_base_syncer_factory()
    syncer2 = mock_base_syncer_factory()

    await run_table_sync(created_table, syncer1, syncer2)

    syncer1.sync_table.assert_awaited_once_with(created_table, refresh_at_start=False)
    syncer2.sync_table.assert_awaited_once_with(created_table, refresh_at_start=True)
