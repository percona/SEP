"""Define tests for the app.sep.sync.syncers.pmm module."""

from unittest.mock import AsyncMock

import pytest

from app.inventory.models import SourceEnum
from app.sep.sync.syncers.pmm import PMMRemoteAPI


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
