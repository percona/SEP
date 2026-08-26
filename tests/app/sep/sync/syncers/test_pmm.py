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

"""Define tests for the app.sep.sync.syncers.pmm module."""

from collections import defaultdict
from collections.abc import Iterator
from typing import Any
from unittest.mock import ANY, AsyncMock, Mock

import pytest
import pytest_asyncio
from pydantic import ValidationError

from app.core.utils.date_time import utc_now
from app.inventory.models import Service, ServiceTypeEnum, SourceEnum
from app.sep.clients.pmm import (
    PMMFetchDiagnostics,
    PMMInventorySnapshot,
    PMMRemoteAPI,
)
from app.sep.crud import (
    SyncEntityAbsenceManager,
    SyncInstanceManager,
    SyncItemManager,
)
from app.sep.inventory import CreatedNode, CreatedService, Node
from app.sep.models import (
    SyncInstance,
    SyncInventoryEntityTypeEnum,
    SyncStatusEnum,
)
from app.sep.sync.syncers.pmm import PMMSyncer
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedServiceFactory,
    MOCK_CREATED_NODE_ID,
)


def _make_validation_error(title: str = "ValidationError") -> ValidationError:
    return ValidationError.from_exception_data(
        title,
        [
            {
                "type": "missing",
                "loc": ("field",),
                "msg": "Field required",
                "input": {},
            }
        ],
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


@pytest.fixture
def mock_request(mocker) -> AsyncMock:
    """Mock request object."""
    return mocker.patch.object(PMMRemoteAPI, "request", new_callable=AsyncMock)


@pytest.fixture
def mock_logger(mocker) -> Mock:
    """Mock logger object."""
    return mocker.patch("app.sep.clients.pmm.PMMRemoteAPI.logger")


@pytest.fixture
def mock_get_version(mocker) -> AsyncMock:
    """Mock get_version method."""
    return mocker.patch(
        "app.sep.clients.pmm.PMMRemoteAPI.get_version", new_callable=AsyncMock
    )


@pytest.fixture
def pmm_remote_api() -> Iterator[PMMRemoteAPI]:
    """Yield a PMMRemoteAPI instance, clearing its version cache on teardown."""
    pmm_remote_api = PMMRemoteAPI(endpoint="http://localhost", api_key="test-key")
    yield pmm_remote_api
    pmm_remote_api.is_older_than_v3.cache_clear()


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
            "app.sep.clients.pmm.PMMRemoteAPI.get_services",
            new=AsyncMock(return_value=created_services),
        )

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
        mock_get_services.assert_awaited_once_with(
            node_id=node_id, skip_failed=True, filter_=None
        )

    @pytest.mark.asyncio
    async def test_get_node_skip_failed_services_false_passes_through(
        self,
        mock_request,
        mock_get_version,
        mock_get_services,
        created_services,
        pmm_remote_api,
    ):
        """Test get_node passes skip_failed_services=False down to get_services."""
        mock_get_version.return_value = "3.0.0"
        node_id = "node-123"
        mock_request.return_value = {
            "Generic": {"node_id": node_id, "name": "Test Node", "address": "localhost"}
        }

        node = await pmm_remote_api.get_node(node_id, skip_failed_services=False)

        assert node.external_id == node_id
        mock_get_services.assert_awaited_once_with(
            node_id=node_id, skip_failed=False, filter_=None
        )

    @pytest.mark.asyncio
    async def test_get_node_with_filter_excludes_node_when_filter_returns_false(
        self,
        mock_request,
        mock_get_version,
        mock_get_services,
        pmm_remote_api,
    ):
        """Test get_node returns None when filter_ is provided and returns False."""
        mock_get_version.return_value = "3.0.0"
        node_id = "node-123"
        mock_request.return_value = {
            "Generic": {
                "node_id": node_id,
                "name": "Test Node",
                "address": "localhost",
                "custom_labels": {"sep_sync": "disabled"},
            }
        }

        def filter_exclude_disabled(item: dict) -> bool:
            labels = item.get("labels") or item.get("custom_labels") or {}
            return labels.get("sep_sync") != "disabled"

        node = await pmm_remote_api.get_node(node_id, filter_=filter_exclude_disabled)

        assert node is None
        mock_get_services.assert_not_awaited()

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

    @pytest.mark.asyncio
    async def test_get_service_with_filter_excludes_service_when_filter_returns_false(
        self,
        mock_request,
        mock_get_version,
        pmm_remote_api,
    ):
        """Test get_service returns None when filter_ is provided and returns False."""
        mock_get_version.return_value = "3.0.0"
        service_id = "service-123"
        mock_request.return_value = {
            "mysql": {
                "service_id": service_id,
                "name": "Test Service",
                "node_id": "node-123",
                "custom_labels": {"sep_sync": "disabled"},
            },
        }

        def filter_exclude_disabled(item: dict) -> bool:
            labels = item.get("labels") or item.get("custom_labels") or {}
            return labels.get("sep_sync") != "disabled"

        service = await pmm_remote_api.get_service(
            service_id, filter_=filter_exclude_disabled
        )

        assert service is None

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

    @pytest.mark.asyncio
    async def test_get_services_includes_valkey(
        self, mock_request, mock_get_version, pmm_remote_api
    ):
        """Test Valkey services validate and sync instead of being skipped."""
        mock_get_version.return_value = "3.0.0"
        mock_request.return_value = {
            "valkey": [
                {"service_id": "valkey-1", "name": "Valkey 1", "node_id": "node-1"},
            ],
        }

        services = await pmm_remote_api.get_services()

        assert len(services) == 1
        assert services[0].type is ServiceTypeEnum.VALKEY
        assert services[0].type.value == "valkey"

        pmm_remote_api.is_older_than_v3.cache_clear()

    @pytest.mark.asyncio
    async def test_get_services_skip_failed_true_logs_and_filters(
        self, mock_request, mock_get_version, mock_logger, pmm_remote_api, mocker
    ):
        """Test get_services skips invalid services when skip_failed=True."""
        mock_get_version.return_value = "3.0.0"
        mock_request.return_value = {
            "mysql": [
                {"service_id": "service-ok", "name": "OK", "node_id": "node-1"},
                {"service_id": "service-bad", "name": "BAD", "node_id": "node-2"},
            ]
        }
        expected_service_count = 2

        def _validate_side_effect(payload: dict):
            if payload.get("service_id") == "service-bad":
                raise _make_validation_error("PMMService")
            return Mock(
                external_id=payload.get("service_id"),
                node_id=payload.get("node_id"),
                type=payload.get("type"),
            )

        validate = mocker.patch(
            "app.sep.clients.pmm.PMMService.model_validate",
            side_effect=_validate_side_effect,
        )

        services = await pmm_remote_api.get_services(skip_failed=True)

        assert [s.external_id for s in services] == ["service-ok"]
        assert validate.call_count == expected_service_count
        mock_logger.exception.assert_called()

    @pytest.mark.asyncio
    async def test_get_services_skip_failed_false_raises(
        self, mock_request, mock_get_version, mock_logger, pmm_remote_api, mocker
    ):
        """Test get_services raises ValidationError when skip_failed=False."""
        mock_get_version.return_value = "3.0.0"
        mock_request.return_value = {
            "mysql": [
                {"service_id": "service-ok", "name": "OK", "node_id": "node-1"},
                {"service_id": "service-bad", "name": "BAD", "node_id": "node-2"},
            ]
        }

        def _validate_side_effect(payload: dict):
            if payload.get("service_id") == "service-bad":
                raise _make_validation_error("PMMService")
            return Mock(
                external_id=payload.get("service_id"),
                node_id=payload.get("node_id"),
                type=payload.get("type"),
            )

        mocker.patch(
            "app.sep.clients.pmm.PMMService.model_validate",
            side_effect=_validate_side_effect,
        )

        with pytest.raises(ValidationError):
            await pmm_remote_api.get_services(skip_failed=False)

        mock_logger.exception.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_services_filters_sep_sync_disabled(
        self, mock_request, mock_get_version, pmm_remote_api, mocker
    ):
        """Test get_services filters out services with sep_sync: disabled label."""
        mock_get_version.return_value = "3.0.0"
        mock_request.return_value = {
            "mysql": [
                {
                    "service_id": "service-1",
                    "name": "Service 1",
                    "node_id": "node-1",
                    "custom_labels": {"sep_sync": "disabled"},
                },
                {
                    "service_id": "service-2",
                    "name": "Service 2",
                    "node_id": "node-2",
                    "custom_labels": {"sep_sync": "enabled"},
                },
                {
                    "service_id": "service-3",
                    "name": "Service 3",
                    "node_id": "node-3",
                },
            ]
        }

        def _validate_side_effect(payload: dict):
            return Mock(
                external_id=payload.get("service_id"),
                node_id=payload.get("node_id"),
                type=payload.get("type"),
                custom_labels=payload.get("custom_labels"),
            )

        mocker.patch(
            "app.sep.clients.pmm.PMMService.model_validate",
            side_effect=_validate_side_effect,
        )

        services = await pmm_remote_api.get_services(
            filter_=PMMSyncer._filter_sep_sync_disabled
        )

        assert {s.external_id for s in services} == {"service-2", "service-3"}

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

        mock_get_services.assert_awaited_once_with(
            skip_failed=True, filter_=None, diagnostics=None
        )

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
        mock_get_services.assert_awaited_once_with(
            skip_failed=True, filter_=None, diagnostics=ANY
        )

    @pytest.mark.asyncio
    async def test_get_nodes_skip_failed_true_logs_and_filters(
        self, mock_request, mock_get_version, mock_logger, pmm_remote_api, mocker
    ):
        """Test get_nodes skips invalid nodes when skip_failed=True."""
        mock_get_version.return_value = "3.0.0"
        mocker.patch.object(
            PMMRemoteAPI,
            "get_services_by_node_external_id",
            new=AsyncMock(return_value=defaultdict(list)),
        )
        mock_request.return_value = {
            "Generic": [
                {"node_id": "good", "name": "Good", "address": "localhost"},
                # No address: fails ``Node`` validation.
                {"node_id": "bad", "name": "Bad"},
            ]
        }

        nodes = await pmm_remote_api.get_nodes(skip_failed=True)

        assert [n.external_id for n in nodes] == ["good"]
        mock_logger.exception.assert_called()

    @pytest.mark.asyncio
    async def test_get_nodes_skip_failed_false_raises(
        self, mock_request, mock_get_version, mock_logger, pmm_remote_api, mocker
    ):
        """Test get_nodes raises ValidationError when skip_failed=False."""
        mock_get_version.return_value = "3.0.0"
        mocker.patch.object(
            PMMRemoteAPI,
            "get_services_by_node_external_id",
            new=AsyncMock(return_value=defaultdict(list)),
        )
        mock_request.return_value = {
            "Generic": [
                {"node_id": "good", "name": "Good", "address": "localhost"},
                # No address: fails ``Node`` validation.
                {"node_id": "bad", "name": "Bad"},
            ]
        }

        with pytest.raises(ValidationError):
            await pmm_remote_api.get_nodes(skip_failed=False)

        mock_logger.exception.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_nodes_with_filter_excludes_nodes_when_filter_returns_false(
        self, mock_request, mock_get_version, pmm_remote_api, mocker
    ):
        """Test get_nodes excludes nodes for which filter_ returns False."""
        mock_get_version.return_value = "3.0.0"
        mocker.patch.object(
            PMMRemoteAPI,
            "get_services_by_node_external_id",
            new=AsyncMock(return_value=defaultdict(list)),
        )
        mock_request.return_value = {
            "Generic": [
                {
                    "node_id": "node-1",
                    "name": "Node 1",
                    "address": "localhost",
                    "custom_labels": {"sep_sync": "disabled"},
                },
                {
                    "node_id": "node-2",
                    "name": "Node 2",
                    "address": "localhost",
                    "custom_labels": {"sep_sync": "enabled"},
                },
                {
                    "node_id": "node-3",
                    "name": "Node 3",
                    "address": "localhost",
                },
            ]
        }

        def filter_exclude_disabled(item: dict) -> bool:
            labels = item.get("labels") or item.get("custom_labels") or {}
            return labels.get("sep_sync") != "disabled"

        nodes = await pmm_remote_api.get_nodes(filter_=filter_exclude_disabled)

        assert {n.external_id for n in nodes} == {"node-2", "node-3"}

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

    @pytest.mark.asyncio
    async def test_get_version(self, mock_request, pmm_remote_api):
        """Test getting the PMM version from the PMM API."""
        mock_request.return_value = {"version": "3.0.0"}

        version = await pmm_remote_api.get_version()

        assert version == "3.0.0"
        mock_request.assert_awaited_once_with("GET", "/v1/version")


class TestPMMSyncerFilter:
    """Test PMMSyncer _filter_sep_sync_disabled and filter usage."""

    @pytest.mark.parametrize(
        ("item", "expected"),
        [
            ({"custom_labels": {"sep_sync": "disabled"}}, False),
            ({"labels": {"sep_sync": "disabled"}}, False),
            ({"custom_labels": {"sep_sync": "enabled"}}, True),
            ({"custom_labels": {}}, True),
            ({}, True),
            ({"labels": {"other": "value"}}, True),
            (
                {
                    "labels": {"other": "value"},
                    "custom_labels": {"sep_sync": "disabled"},
                },
                False,
            ),
            (
                {
                    "labels": {"sep_sync": "enabled"},
                    "custom_labels": {"sep_sync": "disabled"},
                },
                False,
            ),
        ],
    )
    def test_filter_sep_sync_disabled(self, item, expected):
        """Test _filter_sep_sync_disabled excludes only items with sep_sync: disabled."""
        assert PMMSyncer._filter_sep_sync_disabled(item) is expected


@pytest.mark.asyncio
async def test_fetch_node(created_node, pmmsyncer):
    """Test fetching updated data for a specific node."""
    pmmsyncer.break_on_error = False
    pmmsyncer.pmm_api.get_node = AsyncMock(
        return_value=Node(
            external_id=created_node.external_id,
            address="localhost",
            name="Remote Node",
        )
    )

    node = await pmmsyncer.fetch_node(created_node)

    assert node.name == "Remote Node"
    pmmsyncer.pmm_api.get_node.assert_awaited_once_with(
        created_node.external_id,
        skip_failed_services=True,
        filter_=pmmsyncer._filter_sep_sync_disabled,
    )


@pytest.mark.asyncio
async def test_fetch_node_break_on_error_true_does_not_skip_failed_services(
    created_node, pmmsyncer
):
    """Test fetch_node passes skip_failed_services=False when break_on_error=True."""
    pmmsyncer.break_on_error = True
    pmmsyncer.pmm_api.get_node = AsyncMock(
        return_value=Node(
            external_id=created_node.external_id,
            address="localhost",
            name="Remote Node",
        )
    )

    await pmmsyncer.fetch_node(created_node)

    pmmsyncer.pmm_api.get_node.assert_awaited_once_with(
        created_node.external_id,
        skip_failed_services=False,
        filter_=pmmsyncer._filter_sep_sync_disabled,
    )


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
    pmmsyncer.pmm_api.get_service.assert_awaited_once_with(
        created_service.external_id,
        filter_=pmmsyncer._filter_sep_sync_disabled,
    )


@pytest.mark.asyncio
async def test_perform_service_sync(created_service, created_node, pmmsyncer):
    """Test synchronizing data for a specific service."""
    updated_service = Service(
        external_id=created_service.external_id,
        type=ServiceTypeEnum.MYSQL,
        name="Remote Service",
    )
    pmmsyncer.inventory_api.get.side_effect = [
        {"items": [created_node.model_dump()], "total": 1, "offset": 0, "limit": 50},
    ]
    pmmsyncer.inventory_api.put.side_effect = [created_service.model_dump()]

    await pmmsyncer.perform_service_sync(created_service, updated_service)

    pmmsyncer.inventory_api.put.assert_awaited_once()
    expected_url = f"/services/{created_service.id}"
    assert pmmsyncer.inventory_api.put.call_args.args[0] == expected_url


@pytest.mark.asyncio
async def test_perform_node_sync(node_with_services, owned_pmmsyncer, mocker):
    """Test synchronizing data for a specific node."""
    created_node = node_with_services
    updated_node = Node(
        id=created_node.id + 1,
        external_id=created_node.external_id,
        source=SourceEnum.PMM,
        name="Remote Node",
        type="Generic",
        address="localhost",
    )
    owned_pmmsyncer.inventory_api.put.side_effect = [created_node.model_dump()]
    retire_service = mocker.patch(
        "app.sep.sync.syncers.pmm.PMMSyncer.retire_service", new_callable=AsyncMock
    )

    await owned_pmmsyncer.perform_node_sync(created_node, updated_node)

    owned_pmmsyncer.inventory_api.put.assert_awaited_once()
    # Outside a full inventory generation there is nothing to judge absence
    # against, so the missing service is held rather than retired.
    retire_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_perform_inventory_sync(local_node, owned_pmmsyncer, mocker):
    """Test performing the inventory synchronization process."""
    owned_pmmsyncer.break_on_error = False
    owned_pmmsyncer.inventory_api.get.side_effect = [_local_nodes_payload(local_node)]
    owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(return_value=_snapshot())
    retire_node = mocker.patch(
        "app.sep.sync.syncers.pmm.PMMSyncer.retire_node", new_callable=AsyncMock
    )

    await owned_pmmsyncer.perform_inventory_sync()

    owned_pmmsyncer.inventory_api.get.assert_awaited_once()
    owned_pmmsyncer.pmm_api.get_inventory_snapshot.assert_awaited_once_with(
        skip_failed=True,
        filter_=owned_pmmsyncer._filter_sep_sync_disabled,
    )
    # A single absence never retires: the node is held until grace is spent.
    retire_node.assert_not_awaited()


@pytest.mark.asyncio
async def test_perform_inventory_sync_break_on_error_true_skips_failed_false(
    local_node, owned_pmmsyncer, mocker
):
    """Test perform_inventory_sync passes skip_failed=False when break_on_error=True."""
    owned_pmmsyncer.break_on_error = True
    owned_pmmsyncer.inventory_api.get.side_effect = [_local_nodes_payload(local_node)]
    owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(return_value=_snapshot())
    mocker.patch(
        "app.sep.sync.syncers.pmm.PMMSyncer.retire_node", new_callable=AsyncMock
    )

    await owned_pmmsyncer.perform_inventory_sync()

    owned_pmmsyncer.pmm_api.get_inventory_snapshot.assert_awaited_once_with(
        skip_failed=False,
        filter_=owned_pmmsyncer._filter_sep_sync_disabled,
    )


# ---------------------------------------------------------------------------
# Complete-snapshot reconciliation
# ---------------------------------------------------------------------------


_FETCHES_WITH_RETRY = 2


def _snapshot(*nodes: Node, **diagnostics: Any) -> PMMInventorySnapshot:
    """Build a snapshot whose diagnostics default to a complete generation."""
    return PMMInventorySnapshot(
        nodes=list(nodes),
        diagnostics=PMMFetchDiagnostics(**diagnostics),
    )


def _local_nodes_payload(*created_nodes: CreatedNode) -> dict[str, Any]:
    """Build the paginated inventory-API payload listing ``created_nodes``."""
    return {
        "items": [node.model_dump() for node in created_nodes],
        "total": len(created_nodes),
        "offset": 0,
        "limit": 50,
    }


def _remote_node(created_node: CreatedNode) -> Node:
    """Build the PMM-side counterpart of a locally known node."""
    return Node(
        id=created_node.id,
        external_id=created_node.external_id,
        source=SourceEnum.PMM,
        name="Remote Node",
        type="Generic",
        address="localhost",
    )


@pytest.fixture
def local_node(created_node) -> CreatedNode:
    """Return a locally known node carrying an external ID and no services."""
    created_node.external_id = "pmm-node-1"
    created_node.services = []
    return created_node


@pytest.fixture
def node_with_services(created_node) -> CreatedNode:
    """Return a locally known node whose services carry persistable local IDs."""
    created_node.external_id = "pmm-node-1"
    for local_id, service in enumerate(created_node.services, start=1):
        service.id = local_id
    return created_node


@pytest_asyncio.fixture
async def owned_pmmsyncer(pmmsyncer, session) -> PMMSyncer:
    """Return a syncer bound to a real session and a RUNNING instance it owns."""
    instance = await SyncInstanceManager.save(
        session,
        SyncInstance(syncer=pmmsyncer.get_name(), status=SyncStatusEnum.RUNNING),
    )
    pmmsyncer._session = session
    pmmsyncer.sync_instance = instance
    return pmmsyncer


async def _absence_rows(session, entity_type=SyncInventoryEntityTypeEnum.NODE) -> list:
    """Return the ledger rows recorded for ``entity_type``."""
    return await SyncEntityAbsenceManager.list(session, entity_type=entity_type)


class TestGetInventorySnapshot:
    """Test the fetch-completeness diagnostics on ``get_inventory_snapshot``."""

    @pytest.fixture
    def snapshot_api(self, mock_request, mock_get_version, pmm_remote_api):
        """Return a client whose PMM version is pinned to v3."""
        mock_get_version.return_value = "3.0.0"
        return pmm_remote_api

    @pytest.mark.asyncio
    async def test_records_invalid_service(self, snapshot_api, mock_request):
        """Mark the generation incomplete when validation drops a service."""
        mock_request.side_effect = [
            {"mysql": [{"service_id": "svc-1", "node_id": "node-1"}]},
            {"Generic": [{"node_id": "node-1", "name": "N1", "address": "localhost"}]},
        ]

        snapshot = await snapshot_api.get_inventory_snapshot()

        assert snapshot.diagnostics.invalid_services == 1
        assert snapshot.diagnostics.is_complete is False
        assert [node.external_id for node in snapshot.nodes] == ["node-1"]

    @pytest.mark.asyncio
    async def test_records_invalid_node(self, snapshot_api, mock_request):
        """Mark the generation incomplete when validation drops a node."""
        mock_request.side_effect = [
            {},
            {
                "Generic": [
                    {"node_id": "good", "name": "Good", "address": "localhost"},
                    # No address: fails ``Node`` validation.
                    {"node_id": "bad", "name": "Bad"},
                ]
            },
        ]

        snapshot = await snapshot_api.get_inventory_snapshot()

        assert snapshot.diagnostics.invalid_nodes == 1
        assert snapshot.diagnostics.is_complete is False
        assert [node.external_id for node in snapshot.nodes] == ["good"]

    @pytest.mark.asyncio
    async def test_records_node_with_no_upstream_id(self, snapshot_api, mock_request):
        """Drop an id-less node into the diagnostics rather than POSTing it onward.

        Without an ``external_id`` the node cannot be written to the now-strict
        inventory API, and the sync run has no ``except`` around that POST — so
        counting it here is what keeps one malformed payload from aborting the
        whole generation.
        """
        mock_request.side_effect = [
            {},
            {
                "Generic": [
                    {"node_id": "good", "name": "Good", "address": "localhost"},
                    {"name": "Anonymous", "address": "localhost"},
                ]
            },
        ]

        snapshot = await snapshot_api.get_inventory_snapshot()

        assert snapshot.diagnostics.invalid_nodes == 1
        assert snapshot.diagnostics.is_complete is False
        assert [node.external_id for node in snapshot.nodes] == ["good"]

    @pytest.mark.asyncio
    async def test_records_service_with_blank_upstream_id(
        self, snapshot_api, mock_request
    ):
        """Count a blank ``service_id`` as a drop instead of silencing it to None."""
        mock_request.side_effect = [
            {
                "mysql": [
                    {
                        "service_id": "",
                        "service_name": "Blank",
                        "service_type": "mysql",
                        "node_id": "node-1",
                    }
                ]
            },
            {"Generic": [{"node_id": "node-1", "name": "N1", "address": "localhost"}]},
        ]

        snapshot = await snapshot_api.get_inventory_snapshot()

        assert snapshot.diagnostics.invalid_services == 1
        assert snapshot.diagnostics.is_complete is False

    @pytest.mark.asyncio
    async def test_flags_orphan_services(self, snapshot_api, mock_request):
        """Flag a service whose node never appeared in the node list as orphaned."""
        mock_request.side_effect = [
            {"mysql": [{"service_id": "s", "service_name": "S", "node_id": "ghost"}]},
            {"Generic": [{"node_id": "node-1", "name": "N1", "address": "localhost"}]},
        ]

        snapshot = await snapshot_api.get_inventory_snapshot()

        assert snapshot.diagnostics.orphan_service_node_ids == ["ghost"]
        assert snapshot.diagnostics.is_complete is False

    @pytest.mark.asyncio
    async def test_filtered_node_services_are_not_orphans(
        self, snapshot_api, mock_request
    ):
        """Compute orphans pre-filter, so an excluded node keeps its services."""
        mock_request.side_effect = [
            {"mysql": [{"service_id": "s", "service_name": "S", "node_id": "node-1"}]},
            {
                "Generic": [
                    {
                        "node_id": "node-1",
                        "name": "N1",
                        "address": "localhost",
                        "custom_labels": {"sep_sync": "disabled"},
                    }
                ]
            },
        ]

        snapshot = await snapshot_api.get_inventory_snapshot(
            filter_=PMMSyncer._filter_sep_sync_disabled
        )

        assert snapshot.diagnostics.orphan_service_node_ids == []
        assert snapshot.diagnostics.filtered_node_ids == {"node-1"}
        assert snapshot.diagnostics.is_complete is True

    @pytest.mark.asyncio
    async def test_records_filtered_services(self, snapshot_api, mock_request):
        """Record an excluded service without making the generation incomplete."""
        mock_request.side_effect = [
            {
                "mysql": [
                    {
                        "service_id": "svc-1",
                        "service_name": "S1",
                        "node_id": "node-1",
                        "custom_labels": {"sep_sync": "disabled"},
                    }
                ]
            },
            {"Generic": [{"node_id": "node-1", "name": "N1", "address": "localhost"}]},
        ]

        snapshot = await snapshot_api.get_inventory_snapshot(
            filter_=PMMSyncer._filter_sep_sync_disabled
        )

        assert snapshot.diagnostics.filtered_service_ids == {"svc-1"}
        assert snapshot.diagnostics.is_complete is True

    @pytest.mark.asyncio
    async def test_get_nodes_returns_the_snapshot_node_list(
        self, snapshot_api, mock_request
    ):
        """``get_nodes`` keeps its contract by returning the snapshot's node list."""
        payloads = [
            {"mysql": [{"service_id": "s", "service_name": "S", "node_id": "node-1"}]},
            {"Generic": [{"node_id": "node-1", "name": "N1", "address": "localhost"}]},
        ]

        mock_request.side_effect = list(payloads)
        snapshot = await snapshot_api.get_inventory_snapshot()
        mock_request.side_effect = list(payloads)
        nodes = await snapshot_api.get_nodes()

        assert [node.external_id for node in nodes] == [
            node.external_id for node in snapshot.nodes
        ]
        assert [len(node.services) for node in nodes] == [1]


class TestInventoryGenerationGating:
    """Test that retirement requires a complete generation and spent grace."""

    @pytest.fixture
    def retire_node(self, mocker) -> AsyncMock:
        """Replace the node retirement so the retire decision is seen in isolation."""
        return mocker.patch(
            "app.sep.sync.syncers.pmm.PMMSyncer.retire_node", new_callable=AsyncMock
        )

    @pytest.mark.asyncio
    async def test_validation_failure_retires_nothing(
        self, local_node, owned_pmmsyncer, session, retire_node
    ):
        """Retire nothing when a validation-skipped entity blocks the run."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=_snapshot(invalid_services=1)
        )

        await owned_pmmsyncer.perform_inventory_sync()

        retire_node.assert_not_awaited()
        assert await _absence_rows(session) == []

    @pytest.mark.asyncio
    async def test_real_validation_failure_mid_fetch_retires_nothing(
        self,
        local_node,
        owned_pmmsyncer,
        session,
        retire_node,
        pmm_remote_api,
        mock_request,
        mock_get_version,
    ):
        """Retire nothing when a genuine mid-fetch validation failure occurs.

        The snapshot comes from the real client against a node payload that actually
        fails ``Node`` validation, so the incompleteness driving the gate is observed
        rather than asserted. The locally-known node is absent from the resulting
        node list, so it is a real retirement candidate that the gate must spare.
        """
        mock_get_version.return_value = "3.0.0"
        mock_request.side_effect = [
            {},
            # No ``address``: fails ``Node`` validation, so the list comes back empty.
            {"Generic": [{"node_id": "pmm-node-remote", "name": "Remote"}]},
        ]
        snapshot = await pmm_remote_api.get_inventory_snapshot()
        assert snapshot.diagnostics.invalid_nodes == 1
        assert snapshot.nodes == []

        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=snapshot
        )

        await owned_pmmsyncer.perform_inventory_sync()

        retire_node.assert_not_awaited()
        owned_pmmsyncer.inventory_api.delete.assert_not_awaited()
        assert await _absence_rows(session) == []
        assert owned_pmmsyncer._snapshot_complete is False

    @pytest.mark.asyncio
    async def test_single_absence_does_not_retire(
        self, local_node, owned_pmmsyncer, session, retire_node
    ):
        """Start the count without retiring on one generation reporting absence."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=_snapshot()
        )

        await owned_pmmsyncer.perform_inventory_sync()

        retire_node.assert_not_awaited()
        assert [row.missing_generations for row in await _absence_rows(session)] == [1]

    @pytest.mark.asyncio
    async def test_complete_generation_retires_after_grace(
        self, local_node, owned_pmmsyncer, session, retire_node
    ):
        """Retire the entity on a second consecutive complete generation."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=_snapshot()
        )

        await owned_pmmsyncer.perform_inventory_sync()
        retire_node.assert_not_awaited()
        await owned_pmmsyncer.perform_inventory_sync()

        retire_node.assert_awaited_once()
        assert await _absence_rows(session) == []

    @pytest.mark.asyncio
    async def test_absence_counter_resets_on_reappearance(
        self, local_node, owned_pmmsyncer, session, retire_node
    ):
        """Reset the counter to zero, not to N-1, when an entity reappears."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.inventory_api.put.return_value = local_node.model_dump()
        absent = _snapshot()
        present = _snapshot(_remote_node(local_node))
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            side_effect=[absent, present, absent]
        )

        await owned_pmmsyncer.perform_inventory_sync()
        await owned_pmmsyncer.perform_inventory_sync()
        await owned_pmmsyncer.perform_inventory_sync()

        retire_node.assert_not_awaited()
        assert [row.missing_generations for row in await _absence_rows(session)] == [1]

    @pytest.mark.asyncio
    async def test_incomplete_generation_freezes_the_counter(
        self, local_node, owned_pmmsyncer, session, retire_node
    ):
        """Hold the counter steady when a generation is inconclusive."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            side_effect=[_snapshot(), _snapshot(invalid_nodes=1), _snapshot()]
        )

        await owned_pmmsyncer.perform_inventory_sync()
        await owned_pmmsyncer.perform_inventory_sync()
        retire_node.assert_not_awaited()
        await owned_pmmsyncer.perform_inventory_sync()

        retire_node.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_presence_in_an_incomplete_generation_clears_the_counter(
        self, local_node, owned_pmmsyncer, session, retire_node
    ):
        """Clear the counter for an entity the fetch returned, complete or not.

        Incompleteness makes an *absence* unreliable, never a presence: an entity
        the fetch listed was observed whatever else the fetch missed. Counting the
        absences either side of it would retire an entity that never went away for
        two consecutive generations.
        """
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.inventory_api.put.return_value = local_node.model_dump()
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            side_effect=[
                _snapshot(),
                _snapshot(_remote_node(local_node), invalid_services=1),
                _snapshot(),
            ]
        )

        await owned_pmmsyncer.perform_inventory_sync()
        await owned_pmmsyncer.perform_inventory_sync()
        await owned_pmmsyncer.perform_inventory_sync()

        retire_node.assert_not_awaited()
        assert [row.missing_generations for row in await _absence_rows(session)] == [1]

    @pytest.mark.asyncio
    async def test_cross_list_inconsistency_retries_once_then_marks_incomplete(
        self, local_node, owned_pmmsyncer, session, retire_node
    ):
        """Leave the generation incomplete when orphans persist across fetches."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        orphaned = _snapshot(orphan_service_node_ids=["ghost"])
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            side_effect=[orphaned, orphaned]
        )

        await owned_pmmsyncer.perform_inventory_sync()

        assert (
            owned_pmmsyncer.pmm_api.get_inventory_snapshot.await_count
            == _FETCHES_WITH_RETRY
        )
        retire_node.assert_not_awaited()
        assert await _absence_rows(session) == []

    @pytest.mark.asyncio
    async def test_cross_list_inconsistency_second_fetch_clean_proceeds(
        self, local_node, owned_pmmsyncer, session, retire_node
    ):
        """Restore a complete generation and normal gating after a clean refetch."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            side_effect=[_snapshot(orphan_service_node_ids=["ghost"]), _snapshot()]
        )

        await owned_pmmsyncer.perform_inventory_sync()

        assert (
            owned_pmmsyncer.pmm_api.get_inventory_snapshot.await_count
            == _FETCHES_WITH_RETRY
        )
        retire_node.assert_not_awaited()
        assert [row.missing_generations for row in await _absence_rows(session)] == [1]

    @pytest.mark.asyncio
    async def test_filtered_node_is_held_not_counted(
        self, local_node, owned_pmmsyncer, session, retire_node
    ):
        """Hold a node newly labelled ``sep_sync: disabled`` indefinitely."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        excluded = _snapshot(filtered_node_ids={local_node.external_id})
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=excluded
        )

        await owned_pmmsyncer.perform_inventory_sync()
        await owned_pmmsyncer.perform_inventory_sync()

        retire_node.assert_not_awaited()
        assert await _absence_rows(session) == []

    @pytest.mark.asyncio
    async def test_filtered_service_is_held_not_counted(
        self, node_with_services, owned_pmmsyncer, session, mocker
    ):
        """Hold a service newly labelled ``sep_sync: disabled`` indefinitely.

        The node and service filter paths are separate code, so the node-level
        guarantee does not carry over on its own.
        """
        retire_service = mocker.patch(
            "app.sep.sync.syncers.pmm.PMMSyncer.retire_service", new_callable=AsyncMock
        )
        node_with_services.source = SourceEnum.PMM
        for index, service in enumerate(node_with_services.services, start=1):
            service.external_id = f"pmm-service-{index}"
        excluded = {service.external_id for service in node_with_services.services}
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(node_with_services)
        ]
        owned_pmmsyncer.inventory_api.put.return_value = node_with_services.model_dump()
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=_snapshot(
                _remote_node(node_with_services), filtered_service_ids=excluded
            )
        )

        await owned_pmmsyncer.perform_inventory_sync()
        await owned_pmmsyncer.perform_inventory_sync()

        retire_service.assert_not_awaited()
        assert await _absence_rows(session, SyncInventoryEntityTypeEnum.SERVICE) == []
        # The services really did reach the retire path and were held there.
        held = await SyncItemManager.list(
            session,
            entity_type=SyncInventoryEntityTypeEnum.SERVICE,
            sync_instance_id=owned_pmmsyncer.sync_instance.id,
        )
        assert {item.entity_id for item in held} == {
            service.id for service in node_with_services.services
        }
        assert {item.status for item in held} == {SyncStatusEnum.SUCCESS}

    @pytest.mark.asyncio
    async def test_reclaimed_run_aborts_retire_phase(
        self, local_node, owned_pmmsyncer, session, retire_node
    ):
        """Retire nothing from a run that lost ownership of its instance."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=_snapshot()
        )
        await SyncInstanceManager.update_where(
            session,
            {"status": SyncStatusEnum.FAILED},
            id=owned_pmmsyncer.sync_instance.id,
        )

        await owned_pmmsyncer.perform_inventory_sync()

        retire_node.assert_not_awaited()
        assert await _absence_rows(session) == []

    @pytest.mark.asyncio
    async def test_held_entities_end_success_not_failed(
        self, local_node, owned_pmmsyncer, session, retire_node
    ):
        """Close a held entity's SyncItem so the run does not roll up FAILED."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=_snapshot(invalid_nodes=1)
        )

        await owned_pmmsyncer.perform_inventory_sync()

        items = await SyncItemManager.list(
            session, sync_instance_id=owned_pmmsyncer.sync_instance.id
        )
        assert [item.status for item in items] == [SyncStatusEnum.SUCCESS]

    @pytest.mark.asyncio
    async def test_records_generation_completeness_on_the_run(
        self, local_node, owned_pmmsyncer, retire_node
    ):
        """Carry the completeness verdict for ``__aexit__`` to persist."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=_snapshot(invalid_services=2)
        )

        await owned_pmmsyncer.perform_inventory_sync()

        assert owned_pmmsyncer._snapshot_complete is False


@pytest.mark.parametrize("grace", [0, 1])
def test_syncer_rejects_grace_below_two(mock_remote_api, grace):
    """Reject a grace below two, which collapses to single-absence retirement."""
    with pytest.raises(ValidationError):
        PMMSyncer(
            pmm={"endpoint": "http://localhost", "api_key": "test-key"},
            inventory_api=mock_remote_api,
            missing_grace_generations=grace,
        )


class TestSingleEntitySyncNeverRetires:
    """Test that an operator-triggered single-entity refresh is upsert-only."""

    @pytest.mark.asyncio
    async def test_single_node_sync_never_retires_services(
        self, node_with_services, owned_pmmsyncer, session, mocker
    ):
        """Hold a missing service outside a generation instead of retiring it."""
        retire_service = mocker.patch(
            "app.sep.sync.syncers.pmm.PMMSyncer.retire_service", new_callable=AsyncMock
        )
        owned_pmmsyncer.inventory_api.put.return_value = node_with_services.model_dump()

        await owned_pmmsyncer.sync_node(
            node_with_services, _remote_node(node_with_services)
        )

        assert node_with_services.services
        assert owned_pmmsyncer._generation is None
        retire_service.assert_not_awaited()
        assert await _absence_rows(session, SyncInventoryEntityTypeEnum.SERVICE) == []


class TestTombstoneReconciliation:
    """Test how the syncer reconciles against entities it retired earlier."""

    @pytest.fixture
    def sync_service(self, mocker) -> AsyncMock:
        """Replace per-service syncing so the match decision is seen in isolation."""
        return mocker.patch(
            "app.sep.sync.syncers.pmm.PMMSyncer.sync_service", new_callable=AsyncMock
        )

    @staticmethod
    def _node_reporting(created_node: CreatedNode, **service_fields: Any) -> Node:
        """Build the PMM-side node reporting one service with the given fields."""
        remote = _remote_node(created_node)
        remote.services = [
            {"service_name": "reported", "service_type": "mysql", **service_fields}
        ]
        return Node.model_validate(remote.model_dump() | {"node_name": remote.name})

    @pytest.mark.asyncio
    async def test_inventory_read_opts_into_tombstones(
        self, local_node, owned_pmmsyncer
    ):
        """Read retired nodes, or a reappearance would create a duplicate row."""
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=_snapshot()
        )

        await owned_pmmsyncer.perform_inventory_sync()

        params = owned_pmmsyncer.inventory_api.get.await_args.kwargs["params"]
        assert params["include_retired"] == "true"

    @pytest.mark.asyncio
    async def test_reappearance_under_the_same_external_id_revives_the_row(
        self, local_node, owned_pmmsyncer
    ):
        """Revive the existing row rather than creating a second one."""
        local_node.retired_at = utc_now()
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(local_node)
        ]
        owned_pmmsyncer.inventory_api.put.return_value = local_node.model_dump()
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=_snapshot(_remote_node(local_node))
        )

        await owned_pmmsyncer.perform_inventory_sync()

        owned_pmmsyncer.inventory_api.post.assert_awaited_once_with(
            f"/nodes/{local_node.id}/revive"
        )

    @pytest.mark.asyncio
    async def test_an_active_node_wins_its_external_id_over_a_tombstone(
        self, local_node, owned_pmmsyncer, session
    ):
        """Match the live node, and still account for the tombstone it displaced.

        The unique key admits one active row per external id plus any number of
        tombstones, so a retired-inclusive read returns both. Matching the
        tombstone would attempt a revive the active row's key refuses; dropping
        it from the reconciliation set would leave its SyncItem hanging.
        """
        local_node.retired_at = utc_now()
        replacement = CreatedNodeFactory.build(id=local_node.id + 1)
        replacement.external_id = local_node.external_id
        replacement.services = []
        # Tombstone last, so a plain last-write-wins index would pick it.
        owned_pmmsyncer.inventory_api.get.side_effect = [
            _local_nodes_payload(replacement, local_node)
        ]
        owned_pmmsyncer.inventory_api.put.return_value = replacement.model_dump()
        owned_pmmsyncer.pmm_api.get_inventory_snapshot = AsyncMock(
            return_value=_snapshot(_remote_node(replacement))
        )

        await owned_pmmsyncer.perform_inventory_sync()

        # The live node matched, so no revive was posted and no row was created.
        owned_pmmsyncer.inventory_api.post.assert_not_awaited()
        # The tombstone still reached absence handling, which held it.
        assert await _absence_rows(session) == []
        assert (
            owned_pmmsyncer.sync_items[
                (SyncInventoryEntityTypeEnum.NODE, local_node.id)
            ].status
            == SyncStatusEnum.SUCCESS
        )

    @pytest.mark.asyncio
    async def test_port_fallback_passes_over_a_retired_predecessor(
        self, local_node, owned_pmmsyncer, sync_service
    ):
        """Create a new service rather than claim a tombstone sharing its port."""
        predecessor = CreatedServiceFactory.build(id=7)
        predecessor.external_id = "svc-old"
        predecessor.port = 3306
        predecessor.node_id = local_node.id
        predecessor.retired_at = utc_now()
        local_node.services = [predecessor]
        replacement = CreatedServiceFactory.build(id=8)
        owned_pmmsyncer.inventory_api.put.return_value = local_node.model_dump()
        owned_pmmsyncer.inventory_api.post.return_value = replacement.model_dump()

        await owned_pmmsyncer.perform_node_sync(
            local_node,
            self._node_reporting(local_node, service_id="svc-new", port=3306),
        )

        owned_pmmsyncer.inventory_api.post.assert_awaited_once()
        assert owned_pmmsyncer.inventory_api.post.await_args.args[0] == (
            f"/nodes/{local_node.id}/services/"
        )

    @pytest.mark.asyncio
    async def test_port_fallback_still_matches_a_live_service(
        self, local_node, owned_pmmsyncer, sync_service
    ):
        """Keep matching two live services by port exactly as before."""
        live = CreatedServiceFactory.build(id=7)
        live.external_id = "svc-old"
        live.port = 3306
        live.node_id = local_node.id
        live.retired_at = None
        local_node.services = [live]
        owned_pmmsyncer.inventory_api.put.return_value = local_node.model_dump()

        await owned_pmmsyncer.perform_node_sync(
            local_node,
            self._node_reporting(local_node, service_id="svc-new", port=3306),
        )

        owned_pmmsyncer.inventory_api.post.assert_not_awaited()
        assert sync_service.await_args.args[0].id == live.id
