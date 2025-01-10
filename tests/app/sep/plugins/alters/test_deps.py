"""Define tests for the app.sep.plugins.tasks.deps module."""

from unittest.mock import AsyncMock

import pytest

from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.deps import get_tasks_context
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.plugins.alters.deps import (
    build_alters_task_payload,
    get_alters_task,
    get_alters_task_info,
)
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import GeneratedTask, Task, TaskOwner
from tests.app.factories import (
    AltersCreateFactory,
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
    TaskFactory,
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
def created_node() -> CreatedNode:
    """Return a fake created node."""
    created_node = CreatedNodeFactory.build()
    created_node.address = "localhost"
    return created_node


@pytest.fixture
def created_service(created_node) -> CreatedService:
    """Return a fake created service."""
    created_service = CreatedServiceFactory.build()
    created_service.node = created_node
    created_service.type = ServiceTypeEnum.MYSQL
    return created_service


@pytest.fixture
def created_schema() -> CreatedSchema:
    """Return a fake created Schema."""
    return CreatedSchemaFactory.build()


@pytest.fixture
def created_table() -> CreatedTable:
    """Return a fake created Table."""
    return CreatedTableFactory.build()


@pytest.fixture
def created_alters(created_service, created_schema, created_table) -> AltersCreate:
    """Return a fake created AltersCreate instance."""
    created_alters = AltersCreateFactory.build()
    created_alters.service_id = created_service.id
    created_alters.schema_id = created_schema.id
    created_alters.table_id = created_table.id
    created_alters.alter = "ADD COLUMN new_column INT"
    created_alters.recursion_method = "dsn"
    return created_alters


@pytest.fixture
def created_task() -> Task:
    """Return a fake created task."""
    created_task = TaskFactory.build()
    mock_data = {
        "TaskGroups": [
            {
                "Tasks": [
                    {
                        "Config": {
                            "command": "echo",
                            "args": ["hello", "world"],
                        },
                        "Meta": {
                            "schema_name": "public",
                            "table_name": "example_table",
                        },
                    }
                ]
            }
        ],
        "Constraints": [{"RTarget": "mock_hostname"}],
    }
    created_task.data = mock_data
    return created_task


@pytest.mark.asyncio
async def test_build_alters_task_payload(
    created_alters, created_service, created_schema, created_table, mock_inventory_api
):
    """Test for building the alter task payload from form."""
    mock_inventory_api.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
        ]
    )
    generated_task = await build_alters_task_payload(created_alters, mock_inventory_api)
    assert isinstance(generated_task, GeneratedTask)
    assert generated_task.app == TaskOwner.ALTERS

    commands = generated_task.commands
    assert len(commands) == 1
    assert commands[0]["command"] == "pt-online-schema-change"
    assert "--alter=ADD COLUMN new_column INT" in commands[0]["args"]
    assert "--execute" in commands[0]["args"]


@pytest.mark.asyncio
async def test_get_alters_task(created_task, mock_task_api):
    """Test for fetching and validating a task for the Alters plugin."""
    mock_task_api.get = AsyncMock(side_effect=[created_task.model_dump()])
    alters_task = await get_alters_task(created_task.name, mock_task_api)
    assert isinstance(alters_task, Task)
    assert alters_task.name == created_task.name


def test_get_alters_task_info(created_task):
    """Test for extrating relevant information from a task for the Alters plugin."""
    result = get_alters_task_info(created_task.model_dump())
    assert result == {
        "hostname": "mock_hostname",
        "table": "public.example_table",
    }


@pytest.mark.asyncio
async def test_get_tasks_context(
    created_service, created_schema, mock_inventory_api, mock_task_api
):
    """Test for assembling the template context for task-dependent plugins."""
    mock_inventory_api.get = AsyncMock(
        side_effect=[
            [created_service.model_dump()],
            created_schema.model_dump(),
        ]
    )
    mock_task_api.get = AsyncMock(
        side_effect=[
            [],  # for /{task_name}/periodic/
            [],  # for /{task_name}/history/
            {"address1": "host1", "address2": "host2"},  # for /hosts/
        ]
    )
    context = await get_tasks_context(
        mock_inventory_api, mock_task_api, get_alters_task_info
    )
    assert context["mysql_services"][0]["id"] == created_service.id
    assert context["executor_hosts"] == ["host1", "host2"]
