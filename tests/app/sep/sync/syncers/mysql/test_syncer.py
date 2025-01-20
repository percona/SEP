"""Define tests for the app.sep.sync.mysql.syncer.pmm module."""

import json
from unittest.mock import AsyncMock

import pytest

from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.inventory import (
    CreatedNode,
    CreatedSchema,
    CreatedService,
    CreatedTable,
    Node,
    Schema,
    Service,
    Table,
)
from app.sep.sync.syncers.mysql.syncer import MySQLSyncer
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
    MOCK_CREATED_NODE_ID,
    MOCK_CREATED_SCHEMA_ID,
)


@pytest.fixture
def mock_inventory_api() -> AsyncMock:
    """Mock the InventoryAPI dependency."""
    return AsyncMock(spec=RemoteAPI)


@pytest.fixture
def mock_task_api() -> AsyncMock:
    """Mock the TaskAPI dependency."""
    return AsyncMock(spec=RemoteAPI)


@pytest.fixture
def mock_mysql_syncer(mock_task_api, mock_inventory_api) -> MySQLSyncer:
    """Mock MySQLSyncer instance with mocked APIs."""
    return MySQLSyncer(tasks_api=mock_task_api, inventory_api=mock_inventory_api)


@pytest.fixture
def created_service() -> CreatedService:
    """Return a fake created service."""
    created_service = CreatedServiceFactory.build()
    created_service.node_id = MOCK_CREATED_NODE_ID
    created_service.type = ServiceTypeEnum.MYSQL
    created_service.node = CreatedNode(address="localhost", id=MOCK_CREATED_NODE_ID)
    created_service.port = 8000
    return created_service


@pytest.fixture
def created_node(created_service) -> CreatedNode:
    """Return a fake created node."""
    created_node = CreatedNodeFactory.build()
    created_node.address = "localhost:8000"
    created_node.services = [created_service]
    return created_node


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
async def test_build_script_config(mock_mysql_syncer):
    """Test building the configuration for the MySQL sync script."""
    config_str = mock_mysql_syncer.build_script_config(
        "127.0.0.1",
        "192.168.1.10",
        schema="test_schema",
        table="test_table",
    )
    config = json.loads(config_str)

    assert config["hosts"] == ["127.0.0.1", "192.168.1.10"]
    assert config["ignore_schemas"] == []
    assert config["resolve_localhost"] is True
    assert config["schema"] == "test_schema"
    assert config["table"] == "test_table"


@pytest.mark.asyncio
async def test_get_task_target(mock_mysql_syncer):
    """Test returning the target host for the task from the host."""
    mock_mysql_syncer.force_executor_host = "some_executor_host"

    target = await mock_mysql_syncer.get_task_target("127.0.0.1")
    assert target == "some_executor_host"


@pytest.mark.asyncio
async def test_fetch_node(created_node, mock_mysql_syncer, mocker):
    """Test fetching updated data for a specific node."""
    mock_get_available_hosts = mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.get_available_hosts",
        new_callable=AsyncMock,
    )
    mock_wait_for_task_output = mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.wait_for_task_output",
    )
    mock_get_available_hosts.side_effect = [{"localhost:8000": "hostname"}]
    mock_wait_for_task_output.side_effect = [
        """{
            "localhost:8000": [
                {
                    "name": "users",
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "name", "type": "varchar"},
                        {"name": "email", "type": "varchar"}
                    ]
                }
            ]
        }"""
    ]

    updated_node = await mock_mysql_syncer.fetch_node(created_node)

    mock_wait_for_task_output.assert_called_once()
    assert isinstance(updated_node, Node)


@pytest.mark.asyncio
async def test_fetch_service(created_node, created_service, mock_mysql_syncer, mocker):
    """Test fetching updated data for a specific service."""
    mock_get_available_hosts = mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.get_available_hosts",
        new_callable=AsyncMock,
    )
    mock_wait_for_task_output = mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.wait_for_task_output",
    )
    mock_get_available_hosts.side_effect = [{"localhost:8000": "hostname"}]
    mock_wait_for_task_output.side_effect = [
        """{
            "localhost:8000": [
                {
                    "name": "users",
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "name", "type": "varchar"},
                        {"name": "email", "type": "varchar"}
                    ]
                }
            ]
        }"""
    ]
    updated_service = await mock_mysql_syncer.fetch_service(created_service)
    mock_wait_for_task_output.assert_called_once()
    assert isinstance(updated_service, Service)


@pytest.mark.asyncio
async def test_fetch_schema(created_schema, mock_mysql_syncer, mocker):
    """Test fetching updated data for a specific schema."""
    mock_get_available_hosts = mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.get_available_hosts",
        new_callable=AsyncMock,
    )
    mock_wait_for_task_output = mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.wait_for_task_output",
    )
    mock_get_available_hosts.side_effect = [{"localhost:8000": "hostname"}]
    mock_wait_for_task_output.side_effect = [
        """{
            "name": "users",
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "name", "type": "varchar"},
                {"name": "email", "type": "varchar"}
            ]
        }"""
    ]
    updated_schema = await mock_mysql_syncer.fetch_schema(created_schema)
    mock_wait_for_task_output.assert_called_once()
    assert isinstance(updated_schema, Schema)


@pytest.mark.asyncio
async def test_fetch_table(created_table, mock_mysql_syncer, mocker):
    """Test fetching updated data for a specific table."""
    mock_get_available_hosts = mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.get_available_hosts",
        new_callable=AsyncMock,
    )
    mock_wait_for_task_output = mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.wait_for_task_output",
    )
    mock_get_available_hosts.side_effect = [{"localhost:8000": "hostname"}]
    mock_wait_for_task_output.side_effect = [
        """{
            "name": "users",
            "create": "CREATE TABLE employees ( \
                id INT PRIMARY KEY AUTO_INCREMENT, \
                name VARCHAR(50), \
                email VARCHAR(100) \
            );",
            "keys": {
                "primary": ["id"],
                "unique": ["email"]
            }
        }"""
    ]
    updated_schema = await mock_mysql_syncer.fetch_table(created_table)
    mock_wait_for_task_output.assert_called_once()
    assert isinstance(updated_schema, Table)


@pytest.mark.asyncio
async def test_perform_node_sync(created_node, mock_mysql_syncer, mocker):
    """Test synchronizing data for a specific node."""
    updated_node = created_node.model_copy()
    updated_node.services = created_node.services.copy()
    updated_node.services.append(
        CreatedService(
            id=created_node.services[0].id + 1,
            node_id=created_node.services[0].node_id,
            type=ServiceTypeEnum.MYSQL,
            port=created_node.services[0].port,
        )
    )
    expected_sync_call_count = 2
    mock_sync_service = mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.sync_service",
        new_callable=AsyncMock,
    )
    await mock_mysql_syncer.perform_node_sync(created_node, updated_node)
    mock_sync_service.assert_any_await(
        created_node.services[0], updated_node.services[0]
    )
    mock_sync_service.assert_any_await(
        created_node.services[0], updated_node.services[1]
    )
    assert mock_sync_service.await_count == expected_sync_call_count


@pytest.mark.asyncio
async def test_perform_service_sync(
    created_service, created_schema, mock_inventory_api, mock_mysql_syncer, mocker
):
    """Test synchronizing data for a specific service."""
    updated_service = created_service.model_copy()
    updated_service.schemas = [
        CreatedSchema(
            id=MOCK_CREATED_SCHEMA_ID,
            name="updated_schema_name",
            service_id=created_service.schemas[0].service_id,
        ),
    ]
    created_schema.service.node.id = MOCK_CREATED_NODE_ID
    mock_inventory_api.get.side_effect = [
        [created_schema.model_dump()],
    ]
    mock_inventory_api.post.side_effect = [created_schema.model_dump()]
    mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.sync_schema",
        new_callable=AsyncMock,
    )
    mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.delete_schema",
        new_callable=AsyncMock,
    )
    await mock_mysql_syncer.perform_service_sync(created_service, updated_service)
    mock_mysql_syncer.sync_schema.assert_awaited_once()
    mock_mysql_syncer.delete_schema.assert_awaited_once()


@pytest.mark.asyncio
async def test_perform_schema_sync(
    created_schema, mock_inventory_api, mock_mysql_syncer, mocker
):
    """Test synchronize data for a specific schema."""
    updated_schema = created_schema.model_copy()
    updated_table = created_schema.tables[0].model_copy()
    updated_table.name = "updated_table_name"
    updated_schema.tables = [updated_table]
    mock_inventory_api.put.side_effect = [updated_schema.model_dump()]
    mock_inventory_api.post.side_effect = [updated_table.model_dump()]
    mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.sync_table",
        new_callable=AsyncMock,
    )
    mocker.patch(
        "app.sep.sync.syncers.mysql.syncer.MySQLSyncer.delete_table",
        new_callable=AsyncMock,
    )
    await mock_mysql_syncer.perform_schema_sync(created_schema, updated_schema)
    mock_mysql_syncer.sync_table.assert_awaited_once()
    mock_mysql_syncer.delete_table.assert_awaited_once()
