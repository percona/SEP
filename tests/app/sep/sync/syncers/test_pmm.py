"""Define tests for the app.sep.sync.syncers.pmm module."""

from unittest.mock import AsyncMock, Mock

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
    syncer = PMMSyncer(
        pmm={"endpoint": "http://localhost", "api_key": "test-key"},
        inventory_api=mock_remote_api,
    )
    syncer._pmm_api = mock_pmm_api
    return syncer


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


class TestPMMRemoteAPI:
    """Test the PMMRemoteAPI class."""

    @pytest.fixture
    def created_services(self) -> list[CreatedService]:
        """Return a list with fake created services."""
        created_services = []
        for service_id in range(1, 6):
            service = CreatedServiceFactory.build(id=service_id)
            service.node_id = str(service_id)
            created_services.append(service)
        return created_services

    @pytest.fixture
    def mock_get_services(self, mocker, created_services) -> AsyncMock:
        """Mock get_services method."""
        return mocker.patch(
            "app.sep.sync.syncers.pmm.PMMRemoteAPI.get_services",
            new=AsyncMock(return_value=created_services),
        )

    @pytest.fixture
    def mock_request(self, mocker) -> AsyncMock:
        """Mock request object."""
        return mocker.patch.object(PMMRemoteAPI, "request", new_callable=AsyncMock)

    @pytest.fixture
    def mock_logger(self, mocker) -> Mock:
        """Mock logger object."""
        return mocker.patch("app.sep.sync.syncers.pmm.PMMRemoteAPI.logger")

    @pytest.fixture
    def mock_get_version(self, mocker) -> AsyncMock:
        """Mock get_version method."""
        return mocker.patch(
            "app.sep.sync.syncers.pmm.PMMRemoteAPI.get_version", new_callable=AsyncMock
        )

    @pytest.fixture
    def pmm_remote_api(self) -> PMMRemoteAPI:
        """Return a PMMRemoteAPI instance."""
        return PMMRemoteAPI(endpoint="http://localhost", api_key="test-key")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("pmm_version", "expected_method", "expected_path", "expected_kwargs"),
        [
            (
                "2.0.0",
                "POST",
                "/v1/inventory/Nodes/Get",
                {"json": {"node_id": "node-123"}},
            ),
            ("3.0.0", "GET", "/v1/inventory/nodes/node-123", {}),
        ],
    )
    async def test_get_node(
        self,
        mock_request,
        mock_get_version,
        mock_get_services,
        created_services,
        pmm_remote_api,
        pmm_version,
        expected_method,
        expected_path,
        expected_kwargs,
    ):
        """Test retrieving a PMM node by its external ID."""
        mock_get_version.return_value = pmm_version
        node_id = "node-123"
        mock_request.return_value = {
            "Generic": {"node_id": node_id, "name": "Test Node", "address": "localhost"}
        }

        node = await pmm_remote_api.get_node(node_id)

        assert node.external_id == node_id
        assert node.name == "Test Node"
        assert node.type == "Generic"
        assert node.source == SourceEnum.PMM
        assert len(node.services) == len(created_services)
        mock_get_version.assert_awaited_once()
        mock_request.assert_awaited_once_with(
            expected_method, expected_path, **expected_kwargs
        )
        mock_get_services.assert_awaited_once_with(node_id=node_id)

        pmm_remote_api.is_older_than_v3.cache_clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("pmm_version", "expected_method", "expected_path", "expected_kwargs"),
        [
            (
                "2.0.0",
                "POST",
                "/v1/inventory/Services/Get",
                {"json": {"service_id": "service-123"}},
            ),
            ("3.0.0", "GET", "/v1/inventory/services/service-123", {}),
        ],
    )
    async def test_get_service(
        self,
        mock_request,
        mock_get_version,
        pmm_remote_api,
        pmm_version,
        expected_method,
        expected_path,
        expected_kwargs,
    ):
        """Test retrieving a PMM service by its ID."""
        mock_get_version.return_value = pmm_version
        service_id = "service-123"
        mock_request.return_value = {
            "mysql": {
                "service_id": service_id,
                "name": "Test Service",
                "node_id": "node-123",
            },
        }

        service = await pmm_remote_api.get_service(service_id)

        assert service.external_id == service_id
        assert service.type == "mysql"
        mock_get_version.assert_awaited_once()
        mock_request.assert_awaited_once_with(
            expected_method, expected_path, **expected_kwargs
        )

        pmm_remote_api.is_older_than_v3.cache_clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("pmm_version", "expected_method", "expected_path", "expected_kwargs"),
        [
            ("2.0.0", "POST", "/v1/inventory/Services/List", {"json": {}}),
            ("3.0.0", "GET", "/v1/inventory/services", {"params": {}}),
        ],
    )
    async def test_get_services(
        self,
        mock_request,
        mock_get_version,
        pmm_remote_api,
        pmm_version,
        expected_method,
        expected_path,
        expected_kwargs,
    ):
        """Test fetching services from the PMM API."""
        mock_get_version.return_value = pmm_version
        mock_request.return_value = {
            "postgresql": [
                {"service_id": "service-1", "name": "Service 1", "node_id": "node-1"},
                {"service_id": "service-2", "name": "Service 2", "node_id": "node-2"},
            ],
            "mysql": [
                {"service_id": "service-3", "name": "Service 3", "node_id": "node-3"},
            ],
        }

        services = await pmm_remote_api.get_services()
        services.sort(key=lambda service: service.external_id)

        assert services[0].type == "postgresql"
        assert services[1].type == "postgresql"
        assert services[2].type == "mysql"
        mock_get_version.assert_awaited_once()
        mock_request.assert_awaited_once_with(
            expected_method, expected_path, **expected_kwargs
        )

        pmm_remote_api.is_older_than_v3.cache_clear()

    @pytest.mark.asyncio
    async def test_get_services_by_node_external_id(
        self, created_services, pmm_remote_api, mock_get_services
    ):
        """Test the get_services_by_node_external_id method."""
        services_by_node = await pmm_remote_api.get_services_by_node_external_id()

        assert set(services_by_node) == {
            service.node_id for service in created_services
        }
        assert all(len(services) == 1 for services in services_by_node.values())
        assert {
            node_id: services[0].external_id
            for node_id, services in services_by_node.items()
        } == {service.node_id: service.external_id for service in created_services}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("pmm_version", "expected_method", "expected_path", "expected_kwargs"),
        [
            ("2.0.0", "POST", "/v1/inventory/Nodes/List", {"json": {}}),
            ("3.0.0", "GET", "/v1/inventory/nodes", {"params": {}}),
        ],
    )
    async def test_get_nodes(
        self,
        mock_request,
        mock_get_version,
        mock_get_services,
        created_services,
        pmm_remote_api,
        pmm_version,
        expected_method,
        expected_path,
        expected_kwargs,
    ):
        """Test fetching nodes from the PMM API."""
        mock_get_version.return_value = pmm_version
        mock_request.return_value = {
            "Generic": [
                {
                    "node_id": str(service.node_id),
                    "name": f"Node {service.node_id}",
                    "address": "localhost",
                }
                for service in created_services
            ]
        }

        nodes = await pmm_remote_api.get_nodes()

        assert len(nodes) == len(created_services)
        assert {node.external_id for node in nodes} == {
            str(service.node_id) for service in created_services
        }
        assert all(len(node.services) == 1 for node in nodes)
        mock_get_version.assert_awaited_once()
        mock_request.assert_awaited_once_with(
            expected_method, expected_path, **expected_kwargs
        )
        mock_get_services.assert_awaited_once()

        pmm_remote_api.is_older_than_v3.cache_clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("exception", "default_to_v3", "expected_result", "log_arg"),
        [(TypeError, False, True, "v2"), (KeyError, True, False, "v3")],
    )
    async def test_is_older_than_v3_get_version_error(
        self,
        mock_get_version,
        mock_logger,
        pmm_remote_api,
        exception,
        default_to_v3,
        expected_result,
        log_arg,
    ):
        """Test the is_older_than_v3 properly handles expected errors by get_version."""
        mock_get_version.side_effect = exception
        pmm_remote_api.default_to_v3 = default_to_v3

        result = await pmm_remote_api.is_older_than_v3()
        mock_logger.exception.assert_called_once_with(
            "Failed to retrieve PMM version, defaulting to %s", log_arg
        )
        assert result is expected_result
        mock_get_version.assert_awaited_once()

        pmm_remote_api.is_older_than_v3.cache_clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("version", "default_to_v3", "expected_result", "log_arg"),
        [(3, False, True, "v2"), ("invalid", True, False, "v3")],
    )
    async def test_is_older_than_v3_version_parse_error(
        self,
        mock_get_version,
        mock_logger,
        pmm_remote_api,
        version,
        default_to_v3,
        expected_result,
        log_arg,
    ):
        """Test the is_older_than_v3 properly handles expected parse errors by get_version."""
        mock_get_version.return_value = version
        pmm_remote_api.default_to_v3 = default_to_v3

        result = await pmm_remote_api.is_older_than_v3()
        mock_logger.exception.assert_called_once_with(
            "Failed to parse PMM version, defaulting to %s: %s", log_arg, version
        )
        assert result is expected_result
        mock_get_version.assert_awaited_once()

        pmm_remote_api.is_older_than_v3.cache_clear()

    @pytest.mark.asyncio
    async def test_get_version(self, mock_request, pmm_remote_api):
        """Test getting the PMM version from the PMM API."""
        mock_request.return_value = {"version": "3.0.0"}

        version = await pmm_remote_api.get_version()

        assert version == "3.0.0"
        mock_request.assert_awaited_once_with("GET", "/v1/version")


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
