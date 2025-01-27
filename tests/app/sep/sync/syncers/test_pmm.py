"""Define tests for the app.sep.sync.syncers.pmm module."""

from unittest.mock import AsyncMock

import pytest

from app.inventory.models import Service, ServiceTypeEnum, SourceEnum
from app.sep.inventory import CreatedNode, CreatedService, Node
from app.sep.sync.syncers.pmm import PMMRemoteAPI, PMMSyncer
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedServiceFactory,
    MOCK_CREATED_NODE_ID,
)


@pytest.fixture
def mock_pmm_api() -> AsyncMock:
    """Mock the PMMRemoteAPI dependency."""
    return AsyncMock(spec=PMMRemoteAPI)


@pytest.fixture
def pmmsyncer(mock_pmm_api, mock_remote_api) -> PMMSyncer:
    """Mock PMMSyncer instance with mocked APIs."""
    return PMMSyncer(pmm=mock_pmm_api, inventory_api=mock_remote_api)


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
    created_service.node = created_node
    created_service.node_id = created_node.id
    created_service.type = ServiceTypeEnum.MYSQL
    return created_service


@pytest.mark.asyncio
async def test_get_node(mocker):
    """Test retrieving a PMM node by its external ID."""
    mock_post = mocker.patch(
        "app.sep.sync.syncers.pmm.PMMRemoteAPI.post", new_callable=AsyncMock
    )
    node_id = "node-123"
    mock_post.side_effect = [
        {"Generic": {"node_id": node_id, "name": "Test Node", "address": "localhost"}},
        {
            "Generic": [
                {
                    "service_id": "service-1",
                    "name": "Service 1",
                    "node_id": node_id,
                    "type": "mysql",
                }
            ]
        },
    ]

    pmm_remote_api = PMMRemoteAPI(endpoint="http://localhost")
    node = await pmm_remote_api.get_node(node_id)

    assert node.external_id == node_id
    assert node.name == "Test Node"
    assert node.type == "Generic"
    assert node.source == SourceEnum.PMM
    assert len(node.services) == 1

    pmm_remote_api.post.assert_any_call(
        "/v1/inventory/Nodes/Get",
        json={"node_id": node_id},
    )
    pmm_remote_api.post.assert_any_call(
        "/v1/inventory/Services/List",
        json={"node_id": node_id, "service_type": "", "external_group": ""},
    )


@pytest.mark.asyncio
async def test_get_service(mocker):
    """Test retrieving a PMM service by its ID."""
    mock_post = mocker.patch(
        "app.sep.sync.syncers.pmm.PMMRemoteAPI.post", new_callable=AsyncMock
    )
    service_id = "service-123"
    service_data = {
        "mysql": {
            "service_id": service_id,
            "name": "Test Service",
            "node_id": "node-123",
        },
    }

    mock_post.side_effect = [service_data]

    pmm_remote_api = PMMRemoteAPI(endpoint="http://localhost")
    service = await pmm_remote_api.get_service(service_id)

    assert service.external_id == service_id
    assert service.type == "mysql"

    pmm_remote_api.post.assert_called_once_with(
        "/v1/inventory/Services/Get",
        json={"service_id": service_id},
    )


@pytest.mark.asyncio
async def test_get_services(mocker):
    """Test fetching services from the PMM API."""
    mock_post = mocker.patch(
        "app.sep.sync.syncers.pmm.PMMRemoteAPI.post", new_callable=AsyncMock
    )
    services_data = {
        "postgresql": [
            {"service_id": "service-1", "name": "Service 1", "node_id": "node-1"},
            {"service_id": "service-2", "name": "Service 2", "node_id": "node-2"},
        ],
        "mysql": [
            {"service_id": "service-3", "name": "Service 3", "node_id": "node-3"},
        ],
    }

    mock_post.side_effect = [services_data]

    pmm_remote_api = PMMRemoteAPI(endpoint="http://localhost")
    services = await pmm_remote_api.get_services()

    assert services[0].type == "postgresql"
    assert services[1].type == "postgresql"
    assert services[2].type == "mysql"

    pmm_remote_api.post.assert_called_once_with(
        "/v1/inventory/Services/List",
        json={"node_id": "", "service_type": "", "external_group": ""},
    )


@pytest.mark.asyncio
async def test_get_services_by_node_external_id(mocker):
    """Test fetching and grouping services by node ID from the PMM API."""
    mock_post = mocker.patch(
        "app.sep.sync.syncers.pmm.PMMRemoteAPI.post", new_callable=AsyncMock
    )
    services_data = {
        "postgresql": [
            {"service_id": "service-1", "name": "Service 1", "node_id": "node-1"},
            {"service_id": "service-2", "name": "Service 2", "node_id": "node-2"},
        ],
        "mysql": [
            {"service_id": "service-3", "name": "Service 3", "node_id": "node-3"},
        ],
    }

    mock_post.side_effect = [services_data]

    pmm_remote_api = PMMRemoteAPI(endpoint="http://localhost")
    services_by_node = await pmm_remote_api.get_services_by_node_external_id()

    assert len(services_by_node["node-1"]) == 1
    assert len(services_by_node["node-2"]) == 1

    pmm_remote_api.post.assert_called_once_with(
        "/v1/inventory/Services/List",
        json={"node_id": "", "service_type": "", "external_group": ""},
    )


@pytest.mark.asyncio
async def test_get_nodes(mocker):
    """Test fetching nodes from the PMM API."""
    mock_post = mocker.patch(
        "app.sep.sync.syncers.pmm.PMMRemoteAPI.post", new_callable=AsyncMock
    )
    nodes_data = {
        "Generic": [
            {"node_id": "node-1", "name": "Node 1", "address": "localhost"},
            {"node_id": "node-2", "name": "Node 2", "address": "localhost"},
        ]
    }
    services_data = {
        "postgresql": [{"service_id": "service-1", "node_id": "node-1"}],
        "mysql": [{"service_id": "service-2", "node_id": "node-2"}],
    }

    mock_post.side_effect = [
        {"postgresql": services_data["postgresql"], "mysql": services_data["mysql"]},
        nodes_data,
    ]

    pmm_remote_api = PMMRemoteAPI(endpoint="http://localhost")
    nodes = await pmm_remote_api.get_nodes()

    assert nodes[0].external_id == "node-1"
    assert nodes[1].external_id == "node-2"
    assert len(nodes[0].services) == 1
    assert len(nodes[1].services) == 1

    pmm_remote_api.post.assert_any_call(
        "/v1/inventory/Services/List",
        json={"node_id": "", "service_type": "", "external_group": ""},
    )
    pmm_remote_api.post.assert_any_call(
        "/v1/inventory/Nodes/List",
        json={"node_type": ""},
    )


@pytest.mark.asyncio
async def test_fetch_node(created_node, pmmsyncer):
    """Test fetching updated data for a specific node."""
    pmmsyncer.pmm_api.get_node = AsyncMock(
        return_value=Node(
            external_id=created_node.external_id,
            address="localhost",
            name="Remote Node",
        )
    )

    node = await pmmsyncer.fetch_node(created_node)

    assert node.name == "Remote Node"
    pmmsyncer.pmm_api.get_node.assert_awaited_once_with(created_node.external_id)


@pytest.mark.asyncio
async def test_fetch_service(created_service, pmmsyncer):
    """Test fetching updated data for a specific service."""
    pmmsyncer.pmm_api.get_service = AsyncMock(
        return_value=Service(
            external_id=created_service.external_id,
            type=ServiceTypeEnum.MYSQL,
            name="Remote Service",
        )
    )

    service = await pmmsyncer.fetch_service(created_service)

    assert service.name == "Remote Service"
    pmmsyncer.pmm_api.get_service.assert_awaited_once_with(created_service.external_id)


@pytest.mark.asyncio
async def test_perform_service_sync(created_service, created_node, pmmsyncer):
    """Test synchronizing data for a specific service."""
    updated_service = Service(
        external_id=created_service.external_id,
        type=ServiceTypeEnum.MYSQL,
        name="Remote Service",
    )
    pmmsyncer.inventory_api.get.side_effect = [
        [created_node.model_dump()],
    ]
    pmmsyncer.inventory_api.put.side_effect = [created_service.model_dump()]

    await pmmsyncer.perform_service_sync(created_service, updated_service)

    pmmsyncer.inventory_api.put.assert_awaited_once()
    expected_url = f"/services/{created_service.id}"
    assert pmmsyncer.inventory_api.put.call_args.args[0] == expected_url


@pytest.mark.asyncio
async def test_perform_node_sync(created_node, pmmsyncer, mocker):
    """Test synchronizing data for a specific node."""
    updated_node = Node(
        id=created_node.id + 1,
        external_id=created_node.external_id,
        source=SourceEnum.PMM,
        name="Remote Node",
        type="Generic",
        address="localhost",
    )
    pmmsyncer.inventory_api.put.side_effect = [created_node.model_dump()]
    mocker.patch(
        "app.sep.sync.syncers.pmm.PMMSyncer.delete_service", new_callable=AsyncMock
    )
    await pmmsyncer.perform_node_sync(created_node, updated_node)
    pmmsyncer.inventory_api.put.assert_awaited_once()
    pmmsyncer.delete_service.assert_awaited_once()


@pytest.mark.asyncio
async def test_perform_inventory_sync(created_node, pmmsyncer, mocker):
    """Test performing the inventory synchronization process."""
    pmmsyncer.inventory_api.get.side_effect = [[created_node.model_dump()]]
    mock_post = mocker.patch(
        "app.sep.sync.syncers.pmm.PMMRemoteAPI.get", new_callable=AsyncMock
    )
    mock_post.side_effect = [
        {
            "Generic": {
                "node_id": "node_id",
                "name": "Test Node",
                "address": "localhost",
            }
        },
        {
            "Generic": [
                {
                    "service_id": "service-1",
                    "name": "Service 1",
                    "node_id": "node_id",
                    "type": "mysql",
                }
            ]
        },
    ]
    mocker.patch(
        "app.sep.sync.syncers.pmm.PMMSyncer.delete_node", new_callable=AsyncMock
    )
    await pmmsyncer.perform_inventory_sync()
    pmmsyncer.inventory_api.get.assert_awaited_once()
    pmmsyncer.delete_node.assert_awaited_once()
