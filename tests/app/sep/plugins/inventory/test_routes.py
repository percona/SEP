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

"""Define tests for the app.sep.plugins.inventory.routes module."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException, status

from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum, SourceEnum
from app.sep.crud import SyncItemManager
from app.sep.deps import (
    get_created_node,
    get_created_schema,
    get_created_service,
    get_inventory_api,
    get_tasks_api,
)
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.main import sep_app, templates
from app.sep.plugins.inventory.deps import AvailableSyncer, get_syncers
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
    MOCK_CREATED_SCHEMA_ID,
    MOCK_CREATED_SERVICE_ID,
    MOCK_CREATED_TABLE_ID,
)


class _StubPMMSyncer:
    """Stand in for a PMM syncer; capability checks default to ``True``."""

    def can_sync_inventory(self) -> bool:
        return True

    def can_sync_node(self, node: CreatedNode) -> bool:
        return True

    def can_sync_service(self, service: CreatedService) -> bool:
        return True

    def can_sync_schema(self, schema: CreatedSchema) -> bool:
        return True


class _StubMySQLSyncer:
    """Stand in for a MySQL syncer; capability checks default to ``True``."""

    def can_sync_inventory(self) -> bool:
        return True

    def can_sync_node(self, node: CreatedNode) -> bool:
        return True

    def can_sync_service(self, service: CreatedService) -> bool:
        return True

    def can_sync_schema(self, schema: CreatedSchema) -> bool:
        return True


_PMM_STUB_NAME = f"{_StubPMMSyncer.__module__}.{_StubPMMSyncer.__name__}"
_MYSQL_STUB_NAME = f"{_StubMySQLSyncer.__module__}.{_StubMySQLSyncer.__name__}"
_EXPECTED_STUB_COUNT = 2


def _no_syncers() -> list:
    """Resolve ``SyncersDep`` to an empty list for the no-syncers test path."""
    return []


@pytest.fixture
def mock_inventory_api_dep(mock_remote_api: RemoteAPI) -> AsyncMock:
    """Mock the InventoryAPI dependency."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_inventory_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_sync_item_manager(mocker) -> AsyncMock:
    """Mock the SyncItemManager sync_is_running method."""
    return mocker.patch.object(
        SyncItemManager, "sync_is_running", new=AsyncMock(return_value=False)
    )


@pytest.fixture
def mock_syncers() -> list:
    """Override the SyncersDep with two stub syncers."""
    stubs = [_StubPMMSyncer(), _StubMySQLSyncer()]
    sep_app.dependency_overrides[get_syncers] = lambda: stubs
    yield stubs
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_background_tasks():
    """Mock the Background tasks dependency."""
    mock = MagicMock(spec=BackgroundTasks)
    sep_app.dependency_overrides[BackgroundTasks] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_run_sync_funcs(mocker):
    """Replace the ``run_*_sync`` symbols on the routes module with AsyncMocks.

    The real background-task callables open database sessions and invoke
    ``syncer.api_auth(...)``, which the lightweight stub syncers cannot
    satisfy. Patching them at the routes-module level lets the real
    ``BackgroundTasks`` instance schedule and execute the mocks immediately
    after the response, capturing the args originally passed to
    ``add_task``.
    """
    return {
        "inventory": mocker.patch(
            "app.sep.plugins.inventory.routes.run_inventory_sync",
            new=AsyncMock(),
        ),
        "node": mocker.patch(
            "app.sep.plugins.inventory.routes.run_node_sync",
            new=AsyncMock(),
        ),
        "service": mocker.patch(
            "app.sep.plugins.inventory.routes.run_service_sync",
            new=AsyncMock(),
        ),
        "schema": mocker.patch(
            "app.sep.plugins.inventory.routes.run_schema_sync",
            new=AsyncMock(),
        ),
    }


@pytest.fixture
def created_node() -> CreatedNode:
    """Return a fake created node."""
    return CreatedNodeFactory.build()


@pytest.fixture
def _mock_created_node_dep(created_node):
    """Mock the CreatedNodeDep dependency."""
    sep_app.dependency_overrides[get_created_node] = lambda: created_node
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def created_service(created_node) -> CreatedService:
    """Return a fake created service."""
    created_service = CreatedServiceFactory.build()
    created_service.node = created_node
    return created_service


@pytest.fixture
def _mock_created_service_dep(created_service):
    """Mock the CreatedService dependency."""
    sep_app.dependency_overrides[get_created_service] = lambda: created_service
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def created_schema(created_service) -> CreatedSchema:
    """Return a fake created Schema."""
    created_schema = CreatedSchemaFactory.build()
    created_schema.service = created_service
    return created_schema


@pytest.fixture
def _mock_created_schema_dep(created_schema):
    """Mock the CreatedSchema dependency."""
    sep_app.dependency_overrides[get_created_schema] = lambda: created_schema
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def created_table(created_schema) -> CreatedTable:
    """Return a fake created Table."""
    created_table = CreatedTableFactory.build()
    created_table.database = created_schema
    return created_table


@pytest.mark.usefixtures("mock_sync_item_manager", "mock_get_username_mapping")
def test_node_list(test_client, mock_inventory_api_dep, mock_task_api_dep):
    """Test listing nodes."""
    mock_task_api_dep.get.return_value = []
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    mock_inventory_api_dep.get.assert_any_await("/", params={"limit": 0})
    mock_task_api_dep.get.assert_any_await("/periodic/")


@pytest.mark.asyncio
async def test_sync_inventory(async_test_client, mock_syncers, mock_run_sync_funcs):
    """Test syncing inventory without an explicit ``syncer`` form field."""
    response = await async_test_client.post("/inventory/sync/", follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/inventory/"
    mock_run_sync_funcs["inventory"].assert_awaited_once()
    args = mock_run_sync_funcs["inventory"].await_args.args
    assert list(args[1:]) == mock_syncers


@pytest.mark.asyncio
async def test_sync_inventory_with_valid_syncer_param(
    async_test_client, mock_syncers, mock_run_sync_funcs
):
    """Sync only the named syncer when a valid ``syncer`` form field is present."""
    response = await async_test_client.post(
        "/inventory/sync/",
        data={"syncer": _PMM_STUB_NAME},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["inventory"].assert_awaited_once()
    args = mock_run_sync_funcs["inventory"].await_args.args
    assert list(args[1:]) == [mock_syncers[0]]


@pytest.mark.asyncio
async def test_sync_inventory_with_empty_syncer_param_syncs_all(
    async_test_client, mock_syncers, mock_run_sync_funcs
):
    """Treat an empty ``syncer`` form field as a sync-all request."""
    response = await async_test_client.post(
        "/inventory/sync/",
        data={"syncer": ""},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["inventory"].assert_awaited_once()
    args = mock_run_sync_funcs["inventory"].await_args.args
    assert list(args[1:]) == mock_syncers


@pytest.mark.asyncio
async def test_sync_inventory_with_unknown_syncer_param_skips_run(
    async_test_client, mock_syncers, mock_run_sync_funcs
):
    """Reject a POST whose ``syncer`` value matches no configured syncer.

    SEP's global ``HTTPException`` handler converts the raised
    ``HTTPBadRequestException`` into a 303 redirect with a flash message, so
    the assertion focuses on the side effect that matters: the background
    task must not have been scheduled.
    """
    response = await async_test_client.post(
        "/inventory/sync/",
        data={"syncer": "not.a.real.Syncer"},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["inventory"].assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_inventory_with_incapable_syncer_skips_run(
    async_test_client, mocker, mock_run_sync_funcs
):
    """Reject a POST whose syncer matches by name but cannot sync inventory."""
    incapable = _StubPMMSyncer()
    mocker.patch.object(incapable, "can_sync_inventory", return_value=False)
    sep_app.dependency_overrides[get_syncers] = lambda: [incapable]
    try:
        response = await async_test_client.post(
            "/inventory/sync/",
            data={"syncer": _PMM_STUB_NAME},
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        mock_run_sync_funcs["inventory"].assert_not_awaited()
    finally:
        sep_app.dependency_overrides = {}


@pytest.mark.usefixtures(
    "_mock_created_node_dep", "mock_sync_item_manager", "mock_get_username_mapping"
)
def test_node_detail(
    test_client,
    created_node,
):
    """Test retrieving a node's detail page."""
    response = test_client.get(f"/inventory/{created_node.id}")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert created_node.name in response.text


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_node_dep")
async def test_sync_node(
    async_test_client, created_node, mock_syncers, mock_run_sync_funcs
):
    """Sync-all path: every configured syncer is forwarded in declaration order."""
    response = await async_test_client.post(
        f"/inventory/{created_node.id}/sync/", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == f"/inventory/{created_node.id}"
    mock_run_sync_funcs["node"].assert_awaited_once()
    args = mock_run_sync_funcs["node"].await_args.args
    assert list(args[2:]) == mock_syncers


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_node_dep")
async def test_sync_node_with_valid_syncer_param(
    async_test_client, created_node, mock_syncers, mock_run_sync_funcs
):
    """Sync only the named syncer for a node when ``syncer`` is supplied."""
    response = await async_test_client.post(
        f"/inventory/{created_node.id}/sync/",
        data={"syncer": _MYSQL_STUB_NAME},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["node"].assert_awaited_once()
    args = mock_run_sync_funcs["node"].await_args.args
    assert list(args[2:]) == [mock_syncers[1]]


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_node_dep")
async def test_sync_node_with_unknown_syncer_param_skips_run(
    async_test_client, created_node, mock_syncers, mock_run_sync_funcs
):
    """Reject a node sync POST whose syncer name matches no configured syncer."""
    response = await async_test_client.post(
        f"/inventory/{created_node.id}/sync/",
        data={"syncer": "not.a.real.Syncer"},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["node"].assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_node_dep")
async def test_sync_node_without_syncer_param_passes_all_configured_syncers_even_if_one_currently_cannot_sync(
    async_test_client, created_node, mocker, mock_run_sync_funcs
):
    """Pin the refresh-and-chain contract for sync-all node syncs.

    The configured MySQL-style syncer reports it cannot currently sync the
    node (e.g. because it has not yet been turned into a MySQL host by an
    earlier syncer), but the sync-all path must still pass it through. The
    runtime ``run_node_sync`` chain calls each syncer with
    ``refresh_at_start=True`` from the second iteration onward, so a syncer
    whose capability check is currently ``False`` may still become capable
    once an earlier syncer mutates the node.
    """
    pmm_stub = _StubPMMSyncer()
    mysql_stub = _StubMySQLSyncer()
    mocker.patch.object(mysql_stub, "can_sync_node", return_value=False)
    sep_app.dependency_overrides[get_syncers] = lambda: [pmm_stub, mysql_stub]
    try:
        response = await async_test_client.post(
            f"/inventory/{created_node.id}/sync/",
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        mock_run_sync_funcs["node"].assert_awaited_once()
        args = mock_run_sync_funcs["node"].await_args.args
        assert list(args[2:]) == [pmm_stub, mysql_stub]
    finally:
        sep_app.dependency_overrides = {}


def test_node_create(test_client, mock_inventory_api_dep):
    """Test creating a new node."""
    form_data = {
        "address": "127.0.0.1",
        "name": "node_name",
        "external_id": "",
        "source": SourceEnum.PMM,
    }
    response = test_client.post("/inventory/", data=form_data, follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/inventory/"


def test_node_delete(test_client, created_node, mock_inventory_api_dep):
    """Test deleting a node."""
    mock_inventory_api_dep.delete.return_value = AsyncMock()
    response = test_client.post(
        f"/inventory/{created_node.id}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/inventory/"


@pytest.mark.usefixtures(
    "_mock_created_service_dep", "mock_sync_item_manager", "mock_get_username_mapping"
)
def test_service_detail(
    test_client,
    created_service,
):
    """Test retrieving a service's detail page."""
    response = test_client.get(f"/inventory/services/{created_service.id}")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert created_service.name in response.text


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_service_dep")
async def test_sync_service(
    async_test_client, created_service, mock_syncers, mock_run_sync_funcs
):
    """Sync-all path: every configured syncer is forwarded for service sync."""
    response = await async_test_client.post(
        f"/inventory/services/{created_service.id}/sync/", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == f"/inventory/services/{created_service.id}"
    mock_run_sync_funcs["service"].assert_awaited_once()
    args = mock_run_sync_funcs["service"].await_args.args
    assert list(args[2:]) == mock_syncers


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_service_dep")
async def test_sync_service_with_valid_syncer_param(
    async_test_client, created_service, mock_syncers, mock_run_sync_funcs
):
    """Sync only the named syncer for a service when ``syncer`` is supplied."""
    response = await async_test_client.post(
        f"/inventory/services/{created_service.id}/sync/",
        data={"syncer": _PMM_STUB_NAME},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["service"].assert_awaited_once()
    args = mock_run_sync_funcs["service"].await_args.args
    assert list(args[2:]) == [mock_syncers[0]]


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_service_dep")
async def test_sync_service_with_unknown_syncer_param_skips_run(
    async_test_client, created_service, mock_syncers, mock_run_sync_funcs
):
    """Reject a service sync POST with an unknown syncer name."""
    response = await async_test_client.post(
        f"/inventory/services/{created_service.id}/sync/",
        data={"syncer": "not.a.real.Syncer"},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["service"].assert_not_awaited()


@pytest.mark.usefixtures("_mock_created_node_dep")
def test_service_create_for_node(test_client, created_node, mock_inventory_api_dep):
    """Test creating a new service for node."""
    form_data = {
        "environment": "staging",
        "external_id": "",
        "name": "service_name",
        "port": "3306",
        "type": ServiceTypeEnum.MYSQL,
    }
    response = test_client.post(
        f"/inventory/{created_node.id}/services/",
        data=form_data,
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == f"/inventory/{created_node.id}"


def test_service_delete(test_client, created_service, mock_inventory_api_dep):
    """Test deleting a service."""
    mock_inventory_api_dep.get.return_value = created_service.model_dump()
    mock_inventory_api_dep.delete.return_value = {"node_id": created_service.node_id}
    response = test_client.post(
        f"/inventory/services/{created_service.id}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == f"/inventory/{created_service.node_id}"


@pytest.mark.usefixtures(
    "_mock_created_schema_dep", "mock_sync_item_manager", "mock_get_username_mapping"
)
def test_schema_detail(
    test_client,
    created_schema,
):
    """Test retrieving a schema's detail page."""
    response = test_client.get(f"/inventory/schemas/{created_schema.id}")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert created_schema.name in response.text


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_schema_dep")
async def test_sync_schema(
    async_test_client, created_schema, mock_syncers, mock_run_sync_funcs
):
    """Sync-all path: every configured syncer is forwarded for schema sync."""
    response = await async_test_client.post(
        f"/inventory/schemas/{created_schema.id}/sync/", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == f"/inventory/schemas/{created_schema.id}"
    mock_run_sync_funcs["schema"].assert_awaited_once()
    args = mock_run_sync_funcs["schema"].await_args.args
    assert list(args[2:]) == mock_syncers


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_schema_dep")
async def test_sync_schema_with_valid_syncer_param(
    async_test_client, created_schema, mock_syncers, mock_run_sync_funcs
):
    """Sync only the named syncer for a schema when ``syncer`` is supplied."""
    response = await async_test_client.post(
        f"/inventory/schemas/{created_schema.id}/sync/",
        data={"syncer": _MYSQL_STUB_NAME},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["schema"].assert_awaited_once()
    args = mock_run_sync_funcs["schema"].await_args.args
    assert list(args[2:]) == [mock_syncers[1]]


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_schema_dep")
async def test_sync_schema_with_unknown_syncer_param_skips_run(
    async_test_client, created_schema, mock_syncers, mock_run_sync_funcs
):
    """Reject a schema sync POST with an unknown syncer name."""
    response = await async_test_client.post(
        f"/inventory/schemas/{created_schema.id}/sync/",
        data={"syncer": "not.a.real.Syncer"},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["schema"].assert_not_awaited()


def test_schema_create_for_service(
    test_client, created_service, mock_inventory_api_dep
):
    """Test creating a new schema for service."""
    form_data = {"name": "schema_name"}
    response = test_client.post(
        f"/inventory/services/{created_service.id}/schemas/",
        data=form_data,
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == f"/inventory/services/{created_service.id}"


def test_schema_delete(test_client, created_schema, mock_inventory_api_dep):
    """Test deleting a schema."""
    returned_service_id = MOCK_CREATED_SERVICE_ID
    mock_inventory_api_dep.get.return_value = created_schema.model_dump()
    mock_inventory_api_dep.delete.return_value = {"service_id": returned_service_id}
    response = test_client.post(
        f"/inventory/schemas/{created_schema.id}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == f"/inventory/services/{returned_service_id}"


def test_table_create_for_schema(test_client, created_schema, mock_inventory_api_dep):
    """Test creating a new table for schema."""
    form_data = {
        "name": "table_name",
        "create": """CREATE TABLE employees (
            id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(50),
            email VARCHAR(100)
        );""",
    }
    response = test_client.post(
        f"/inventory/schemas/{created_schema.id}/tables/",
        data=form_data,
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER


def test_table_delete(test_client, created_table, mock_inventory_api_dep):
    """Test deleting a table."""
    delete_table_id = MOCK_CREATED_TABLE_ID
    returned_schema_id = MOCK_CREATED_SCHEMA_ID
    mock_inventory_api_dep.get.return_value = created_table.model_dump()
    mock_inventory_api_dep.delete.return_value = {"schema_id": returned_schema_id}
    response = test_client.post(
        f"/inventory/tables/{delete_table_id}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == f"/inventory/schemas/{returned_schema_id}"


class TestCheckServiceConnectivity:
    """Test the check_service_connectivity route."""

    @pytest.fixture
    def mock_tasks_api_dep(self) -> AsyncMock:
        """Mock the TaskAPI dependency for connectivity checks."""
        mock = AsyncMock(spec=RemoteAPI)
        sep_app.dependency_overrides[get_tasks_api] = lambda: mock
        yield mock
        sep_app.dependency_overrides = {}

    @pytest.fixture
    def mysql_service(self, created_node) -> CreatedService:
        """Return a MySQL service with a node and port."""
        service = CreatedServiceFactory.build(type=ServiceTypeEnum.MYSQL, port=3306)
        service.node = created_node
        return service

    @pytest.fixture
    def _mock_mysql_service_dep(self, mysql_service):
        """Mock CreatedServiceDep with a MySQL service."""
        sep_app.dependency_overrides[get_created_service] = lambda: mysql_service
        yield
        sep_app.dependency_overrides = {}

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_connectivity_check_success(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Verify redirect with success flash on a passing connectivity check."""
        mock_tasks_api_dep.post.return_value = {
            "success": True,
            "error": None,
            "task_history_id": 42,
        }
        response = test_client.post(
            f"/inventory/services/{mysql_service.id}/check-connectivity/",
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == f"/inventory/services/{mysql_service.id}"
        mock_tasks_api_dep.post.assert_awaited_once()

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_connectivity_check_failure(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Verify redirect with error flash when connectivity check fails."""
        mock_tasks_api_dep.post.return_value = {
            "success": False,
            "error": "Connection refused",
            "task_history_id": 43,
        }
        response = test_client.post(
            f"/inventory/services/{mysql_service.id}/check-connectivity/",
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == f"/inventory/services/{mysql_service.id}"

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_connectivity_check_tasks_api_error(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Verify redirect with error flash when Tasks API raises an exception."""
        mock_tasks_api_dep.post.side_effect = ConnectionError("timeout")
        response = test_client.post(
            f"/inventory/services/{mysql_service.id}/check-connectivity/",
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == f"/inventory/services/{mysql_service.id}"

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_connectivity_check_service_without_node(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Verify error flash when service has no associated node."""
        mysql_service.node = None
        response = test_client.post(
            f"/inventory/services/{mysql_service.id}/check-connectivity/",
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_connectivity_check_service_without_port(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Verify error flash when service has no port."""
        mysql_service.port = None
        response = test_client.post(
            f"/inventory/services/{mysql_service.id}/check-connectivity/",
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.parametrize(
        "service_type",
        [
            ServiceTypeEnum.PROXYSQL,
            ServiceTypeEnum.HAPROXY,
            ServiceTypeEnum.EXTERNAL,
        ],
    )
    def test_connectivity_check_rejects_unsupported_service_type(
        self,
        test_client,
        created_node,
        mock_tasks_api_dep,
        service_type,
    ):
        """Verify the route rejects unsupported service types server-side."""
        service = CreatedServiceFactory.build(type=service_type, port=3306)
        service.node = created_node
        sep_app.dependency_overrides[get_created_service] = lambda: service
        try:
            response = test_client.post(
                f"/inventory/services/{service.id}/check-connectivity/",
                follow_redirects=False,
            )
        finally:
            sep_app.dependency_overrides.pop(get_created_service, None)
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == f"/inventory/services/{service.id}"
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_connectivity_check_http_exception_surfaces_detail(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Verify HTTPException from Tasks API is handled and does not blow up."""
        mock_tasks_api_dep.post.side_effect = HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nomad unavailable",
        )
        response = test_client.post(
            f"/inventory/services/{mysql_service.id}/check-connectivity/",
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == f"/inventory/services/{mysql_service.id}"

    @pytest.mark.parametrize(
        "service_type",
        [
            ServiceTypeEnum.MYSQL,
            ServiceTypeEnum.POSTGRESQL,
            ServiceTypeEnum.MONGODB,
        ],
    )
    @pytest.mark.usefixtures("mock_sync_item_manager", "mock_get_username_mapping")
    def test_connectivity_button_visible_for_connectable_types(
        self,
        test_client,
        created_node,
        service_type,
    ):
        """Verify the connectivity check button renders for connectable service types."""
        service = CreatedServiceFactory.build(type=service_type, port=3306)
        service.node = created_node
        sep_app.dependency_overrides[get_created_service] = lambda: service
        try:
            response = test_client.get(f"/inventory/services/{service.id}")
            assert response.status_code == status.HTTP_200_OK
            assert "check-connectivity" in response.text
        finally:
            sep_app.dependency_overrides.pop(get_created_service, None)

    @pytest.mark.parametrize(
        "service_type",
        [
            ServiceTypeEnum.PROXYSQL,
            ServiceTypeEnum.HAPROXY,
            ServiceTypeEnum.EXTERNAL,
        ],
    )
    @pytest.mark.usefixtures("mock_sync_item_manager", "mock_get_username_mapping")
    def test_connectivity_button_hidden_for_non_connectable_types(
        self,
        test_client,
        created_node,
        service_type,
    ):
        """Verify the connectivity check button does not render for non-connectable types."""
        service = CreatedServiceFactory.build(type=service_type, port=3306)
        service.node = created_node
        sep_app.dependency_overrides[get_created_service] = lambda: service
        try:
            response = test_client.get(f"/inventory/services/{service.id}")
            assert response.status_code == status.HTTP_200_OK
            assert "check-connectivity" not in response.text
        finally:
            sep_app.dependency_overrides.pop(get_created_service, None)


def _assert_available_syncers_context(template_spy):
    """Assert the spy captured an ``available_syncers`` context list of two stubs."""
    template_spy.assert_called_once()
    _, kwargs = template_spy.call_args
    available = kwargs["context"]["available_syncers"]
    assert len(available) == _EXPECTED_STUB_COUNT
    assert all(isinstance(entry, AvailableSyncer) for entry in available)
    assert {entry.name for entry in available} == {_PMM_STUB_NAME, _MYSQL_STUB_NAME}
    assert {entry.display_name for entry in available} == {"_StubPMM", "_StubMySQL"}
    assert kwargs["context"]["can_sync"] is True


@pytest.mark.usefixtures("mock_sync_item_manager", "mock_get_username_mapping")
def test_node_list_context_has_available_syncers(
    mocker, test_client, mock_inventory_api_dep, mock_task_api_dep, mock_syncers
):
    """Render the node list and assert ``available_syncers`` reaches the template."""
    mock_task_api_dep.get.return_value = []
    template_spy = mocker.spy(templates, "TemplateResponse")
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    _assert_available_syncers_context(template_spy)


@pytest.mark.usefixtures(
    "_mock_created_node_dep", "mock_sync_item_manager", "mock_get_username_mapping"
)
def test_node_detail_context_has_available_syncers(
    mocker, test_client, created_node, mock_syncers
):
    """Render the node detail page and assert the context carries the syncers."""
    template_spy = mocker.spy(templates, "TemplateResponse")
    response = test_client.get(f"/inventory/{created_node.id}")
    assert response.status_code == status.HTTP_200_OK
    _assert_available_syncers_context(template_spy)


@pytest.mark.usefixtures(
    "_mock_created_service_dep", "mock_sync_item_manager", "mock_get_username_mapping"
)
def test_service_detail_context_has_available_syncers(
    mocker, test_client, created_service, mock_syncers
):
    """Render the service detail page and assert the context carries the syncers."""
    template_spy = mocker.spy(templates, "TemplateResponse")
    response = test_client.get(f"/inventory/services/{created_service.id}")
    assert response.status_code == status.HTTP_200_OK
    _assert_available_syncers_context(template_spy)


@pytest.mark.usefixtures(
    "_mock_created_schema_dep", "mock_sync_item_manager", "mock_get_username_mapping"
)
def test_schema_detail_context_has_available_syncers(
    mocker, test_client, created_schema, mock_syncers
):
    """Render the schema detail page and assert the context carries the syncers."""
    template_spy = mocker.spy(templates, "TemplateResponse")
    response = test_client.get(f"/inventory/schemas/{created_schema.id}")
    assert response.status_code == status.HTTP_200_OK
    _assert_available_syncers_context(template_spy)


@pytest.mark.usefixtures("mock_sync_item_manager", "mock_get_username_mapping")
def test_node_list_context_is_empty_when_no_syncers_configured(
    mocker, test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """Render the node list with zero configured syncers — sync UI is hidden."""
    mock_task_api_dep.get.return_value = []
    sep_app.dependency_overrides[get_syncers] = _no_syncers
    template_spy = mocker.spy(templates, "TemplateResponse")
    try:
        response = test_client.get("/inventory/")
        assert response.status_code == status.HTTP_200_OK
        _, kwargs = template_spy.call_args
        assert kwargs["context"]["available_syncers"] == []
        assert kwargs["context"]["can_sync"] is False
    finally:
        sep_app.dependency_overrides = {}
