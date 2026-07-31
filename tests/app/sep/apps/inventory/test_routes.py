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

"""Define tests for the app.sep.apps.inventory.routes module."""

import json
import re
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from pydantic import SecretStr

from app.core.config import settings
from app.core.pagination import MAX_PAGINATION_LIMIT
from app.core.requests import RemoteAPI
from app.core.security import crypto_serializer
from app.inventory.models import ServiceTypeEnum, SourceEnum
from app.sep.apps.inventory.constants import CONNECTABLE_SERVICE_TYPES
from app.sep.apps.inventory.deps import AvailableSyncer, get_syncers
from app.sep.deps import (
    AVAILABLE_TIMEZONES,
    get_created_node,
    get_created_schema,
    get_created_service,
    get_tasks_api,
)
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.main import sep_app, templates
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
    MOCK_CREATED_SCHEMA_ID,
    MOCK_CREATED_SERVICE_ID,
    MOCK_CREATED_TABLE_ID,
)
from tests.app.sep.apps.inventory.conftest import (
    EXPECTED_STUB_COUNT,
    MYSQL_STUB_NAME,
    no_syncers,
    PMM_STUB_NAME,
    StubMySQLSyncer,
    StubPMMSyncer,
)

_UNSUPPORTED_SERVICE_TYPES = sorted(
    set(ServiceTypeEnum) - CONNECTABLE_SERVICE_TYPES, key=str
)


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
    mock_inventory_api_dep.get.return_value = {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 50,
    }
    mock_task_api_dep.get.return_value = []
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    mock_inventory_api_dep.get.assert_any_await(
        "/nodes/", params={"offset": 0, "limit": MAX_PAGINATION_LIMIT}
    )
    mock_task_api_dep.get.assert_any_await("/inventory-sync/periodic/")


def test_jinja_routes_are_omitted_from_openapi():
    """Verify legacy inventory Jinja2 routes are excluded from the OpenAPI schema.

    The React control consumes the new JSON route at
    ``POST /api/apps/inventory/sync/``; the Jinja2 trigger remains
    functional but is hidden from OpenAPI now that the supported API
    surface is JSON-only.
    """
    openapi = sep_app.openapi()
    assert "/inventory/sync/" not in openapi["paths"]
    assert "/inventory/" not in openapi["paths"]


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
        data={"syncer": PMM_STUB_NAME},
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

    The route catches the ``ValueError`` raised by ``filter_syncers_by_name``
    and re-raises it as ``HTTPBadRequestException``, which SEP's global
    ``HTTPException`` handler then converts into a 303 redirect with a flash
    message, so the assertion focuses on the side effect that matters: the
    background task must not have been scheduled.
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
    incapable = StubPMMSyncer()
    mocker.patch.object(incapable, "can_sync_inventory", return_value=False)
    sep_app.dependency_overrides[get_syncers] = lambda: [incapable]
    try:
        response = await async_test_client.post(
            "/inventory/sync/",
            data={"syncer": PMM_STUB_NAME},
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
        data={"syncer": MYSQL_STUB_NAME},
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
    pmm_stub = StubPMMSyncer()
    mysql_stub = StubMySQLSyncer()
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
        data={"syncer": PMM_STUB_NAME},
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
        data={"syncer": MYSQL_STUB_NAME},
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


@pytest.mark.asyncio
async def test_sync_inventory_uses_internal_token(
    async_test_client, mock_syncers, mock_run_sync_funcs, mocker
):
    """The inventory sync background task is scheduled with the internal token."""
    mocker.patch.object(
        settings, "SEP_INTERNAL_TOKEN", SecretStr("route-internal-token")
    )
    response = await async_test_client.post("/inventory/sync/", follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["inventory"].assert_awaited_once()
    assert mock_run_sync_funcs["inventory"].await_args.args[0] == "route-internal-token"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_node_dep")
async def test_sync_node_uses_internal_token(
    async_test_client, created_node, mock_syncers, mock_run_sync_funcs, mocker
):
    """The node sync background task is scheduled with the internal token."""
    mocker.patch.object(
        settings, "SEP_INTERNAL_TOKEN", SecretStr("route-internal-token")
    )
    response = await async_test_client.post(
        f"/inventory/{created_node.id}/sync/", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["node"].assert_awaited_once()
    assert mock_run_sync_funcs["node"].await_args.args[1] == "route-internal-token"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_service_dep")
async def test_sync_service_uses_internal_token(
    async_test_client, created_service, mock_syncers, mock_run_sync_funcs, mocker
):
    """The service sync background task is scheduled with the internal token."""
    mocker.patch.object(
        settings, "SEP_INTERNAL_TOKEN", SecretStr("route-internal-token")
    )
    response = await async_test_client.post(
        f"/inventory/services/{created_service.id}/sync/", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["service"].assert_awaited_once()
    assert mock_run_sync_funcs["service"].await_args.args[1] == "route-internal-token"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_created_schema_dep")
async def test_sync_schema_uses_internal_token(
    async_test_client, created_schema, mock_syncers, mock_run_sync_funcs, mocker
):
    """The schema sync background task is scheduled with the internal token."""
    mocker.patch.object(
        settings, "SEP_INTERNAL_TOKEN", SecretStr("route-internal-token")
    )
    response = await async_test_client.post(
        f"/inventory/schemas/{created_schema.id}/sync/", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_run_sync_funcs["schema"].assert_awaited_once()
    assert mock_run_sync_funcs["schema"].await_args.args[1] == "route-internal-token"


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


def _flashed_texts(response) -> list[str]:
    """Return the flash-message texts the response serialised into the cookie.

    The messages middleware round-trips the queue through a signed ``messages``
    cookie, so this is the only place a redirect's user-visible text is
    observable from a test.
    """
    cookie = response.cookies.get("messages")
    if cookie is None:
        return []
    return [message["t"] for message in json.loads(crypto_serializer.loads(cookie))]


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

    @pytest.fixture
    def _mock_executor_hosts(self, mysql_service, mock_tasks_api_dep):
        """Pre-populate ``GET /hosts/`` so address lookup resolves to the node name.

        The connectivity check resolves the executor target by address before
        posting; tests that exercise the post path need a matching entry in
        the executor hosts mapping or the route short-circuits with an
        "address not registered" flash instead.
        """
        mock_tasks_api_dep.get.return_value = {
            mysql_service.node.name: mysql_service.node.address,
        }

    @pytest.mark.parametrize(
        "service_type",
        [
            ServiceTypeEnum.MYSQL,
            ServiceTypeEnum.POSTGRESQL,
            ServiceTypeEnum.MONGODB,
        ],
    )
    def test_connectivity_check_success(
        self,
        test_client,
        created_node,
        mock_tasks_api_dep,
        service_type,
    ):
        """Verify redirect, success flash, and lowercase ``service_type`` in payload."""
        service = CreatedServiceFactory.build(type=service_type, port=3306)
        service.node = created_node
        sep_app.dependency_overrides[get_created_service] = lambda: service
        mock_tasks_api_dep.get.return_value = {
            service.node.name: service.node.address,
        }
        mock_tasks_api_dep.post.return_value = {
            "success": True,
            "error": None,
            "task_history_id": 42,
        }
        try:
            response = test_client.post(
                f"/inventory/services/{service.id}/check-connectivity/",
                follow_redirects=False,
            )
        finally:
            sep_app.dependency_overrides.pop(get_created_service, None)
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == f"/inventory/services/{service.id}"
        assert _flashed_texts(response) == [
            f"Connectivity check passed for {service.name}"
        ]
        mock_tasks_api_dep.get.assert_awaited_once_with("/hosts/")
        mock_tasks_api_dep.post.assert_awaited_once_with(
            "/connectivity-check/",
            json={
                "target": service.node.name,
                "host": service.node.address,
                "port": service.port,
                "service_type": service_type.value,
            },
        )

    def test_connectivity_check_resolves_executor_name_by_address(
        self,
        test_client,
        created_node,
        mock_tasks_api_dep,
    ):
        """Reproduce the case where inventory name and executor name differ.

        When the inventory display name does not match the Nomad node name,
        the connectivity check must look the executor target up by address
        (the same reconciliation the host dropdown does) instead of passing
        the inventory name straight through.
        """
        service = CreatedServiceFactory.build(type=ServiceTypeEnum.MYSQL, port=3306)
        service.node = created_node
        executor_node_name = f"{created_node.name}-nomad-mismatch"
        sep_app.dependency_overrides[get_created_service] = lambda: service
        mock_tasks_api_dep.get.return_value = {
            executor_node_name: service.node.address,
        }
        mock_tasks_api_dep.post.return_value = {
            "success": True,
            "error": None,
            "task_history_id": 42,
        }
        try:
            response = test_client.post(
                f"/inventory/services/{service.id}/check-connectivity/",
                follow_redirects=False,
            )
        finally:
            sep_app.dependency_overrides.pop(get_created_service, None)
        assert response.status_code == status.HTTP_303_SEE_OTHER
        mock_tasks_api_dep.post.assert_awaited_once_with(
            "/connectivity-check/",
            json={
                "target": executor_node_name,
                "host": service.node.address,
                "port": service.port,
                "service_type": ServiceTypeEnum.MYSQL.value,
            },
        )

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_connectivity_check_address_not_registered(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Surface a flash and skip the API call when no executor matches the address."""
        mock_tasks_api_dep.get.return_value = {"some-other-nomad": "10.0.0.99"}
        response = test_client.post(
            f"/inventory/services/{mysql_service.id}/check-connectivity/",
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == f"/inventory/services/{mysql_service.id}"
        assert _flashed_texts(response) == [
            f"Connectivity check failed for {mysql_service.name}: "
            f"no executor host is registered for address "
            f"{mysql_service.node.address!r} (inventory node {mysql_service.node.name!r})."
        ]
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_connectivity_check_executor_hosts_fetch_fails(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Surface a flash and skip the API call when fetching hosts fails."""
        mock_tasks_api_dep.get.side_effect = ConnectionError("tasks unreachable")
        response = test_client.post(
            f"/inventory/services/{mysql_service.id}/check-connectivity/",
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert _flashed_texts(response) == [
            f"Connectivity check failed for {mysql_service.name}: "
            "could not reach the Tasks API"
        ]
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_connectivity_check_executor_hosts_http_exception_surfaces_detail(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Surface the upstream ``detail`` when the executor-hosts GET raises HTTPException.

        Pin the GET-path counterpart of
        :meth:`test_connectivity_check_http_exception_surfaces_detail` so the
        ``except HTTPException`` branch keeps forwarding ``exc.detail`` into
        the flash message verbatim, instead of falling through to the generic
        "could not reach the Tasks API" string from the bare ``except``.
        """
        mock_tasks_api_dep.get.side_effect = HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nomad unavailable",
        )
        response = test_client.post(
            f"/inventory/services/{mysql_service.id}/check-connectivity/",
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == f"/inventory/services/{mysql_service.id}"
        assert _flashed_texts(response) == [
            f"Connectivity check failed for {mysql_service.name}: Nomad unavailable"
        ]
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.usefixtures("_mock_mysql_service_dep", "_mock_executor_hosts")
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
        assert _flashed_texts(response) == [
            f"Connectivity check failed for {mysql_service.name}: Connection refused"
        ]

    @pytest.mark.usefixtures("_mock_mysql_service_dep", "_mock_executor_hosts")
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
        assert _flashed_texts(response) == [
            f"Connectivity check failed for {mysql_service.name}: "
            "could not reach the Tasks API"
        ]

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
        assert _flashed_texts(response) == [
            f"Connectivity check failed for {mysql_service.name}: "
            "missing node or port information"
        ]
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
        assert _flashed_texts(response) == [
            f"Connectivity check failed for {mysql_service.name}: "
            "missing node or port information"
        ]
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.parametrize("service_type", _UNSUPPORTED_SERVICE_TYPES)
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
        assert _flashed_texts(response) == [
            f"Connectivity check is not supported for {service_type.name} services"
        ]
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.usefixtures("_mock_mysql_service_dep", "_mock_executor_hosts")
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
        assert _flashed_texts(response) == [
            f"Connectivity check failed for {mysql_service.name}: Nomad unavailable"
        ]

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

    @pytest.mark.parametrize("service_type", _UNSUPPORTED_SERVICE_TYPES)
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
    assert len(available) == EXPECTED_STUB_COUNT
    assert all(isinstance(entry, AvailableSyncer) for entry in available)
    assert {entry.name for entry in available} == {PMM_STUB_NAME, MYSQL_STUB_NAME}
    assert {entry.display_name for entry in available} == {"StubPMM", "StubMySQL"}
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
    sep_app.dependency_overrides[get_syncers] = no_syncers
    template_spy = mocker.spy(templates, "TemplateResponse")
    try:
        response = test_client.get("/inventory/")
        assert response.status_code == status.HTTP_200_OK
        _, kwargs = template_spy.call_args
        assert kwargs["context"]["available_syncers"] == []
        assert kwargs["context"]["can_sync"] is False
    finally:
        sep_app.dependency_overrides = {}


_INVENTORY_SYNC_PERIODIC_ID = 7


def _compact(text: str) -> str:
    """Collapse whitespace runs in rendered HTML for substring assertions.

    The djlint formatter splits HTML attributes onto separate lines in the
    template source; the rendered output preserves that whitespace, so plain
    substring matches against multi-attribute fragments fail. Normalising any
    run of whitespace to a single space lets tests assert against the logical
    content without binding to formatter output.

    :param text: The rendered HTML body.
    :type text: str
    :return: The body with consecutive whitespace collapsed to single spaces.
    :rtype: str
    """
    return re.sub(r"\s+", " ", text)


def _execute_request_for(syncer: str | None) -> dict | None:
    """Build the ``execute_request`` blob for a periodic-task fake row.

    :param syncer: Fully qualified syncer name to embed in ``meta``, or
        ``None`` to omit ``execute_request`` entirely (legacy / sync-all rows).
    :type syncer: str | None
    :return: A JSON-serialisable ``execute_request`` dict, or ``None``.
    :rtype: dict | None
    """
    if syncer is None:
        return None
    return {
        "task": "inventory-sync",
        "target": "local",
        "meta": {"syncer": syncer},
        "payload": None,
        "tracking": {"allocation_id": None, "evaluation_id": None},
        "eta": None,
    }


def _interval_periodic(
    *,
    every: int = 5,
    period: str = "minutes",
    enabled: bool = True,
    task_id: int = _INVENTORY_SYNC_PERIODIC_ID,
    syncer: str | None = None,
) -> dict:
    """Build a fake interval-mode inventory-sync periodic-task JSON row."""
    return {
        "id": task_id,
        "name": "inventory-sync",
        "task": "inventory-sync",
        "start_time": None,
        "enabled": enabled,
        "description": "",
        "execute_request": _execute_request_for(syncer),
        "interval": {"every": every, "period": period},
        "crontab": None,
        "last_run_at": None,
        "total_run_count": 0,
        "date_changed": None,
        "next_run_at": None,
        "period": f"every {every} {period[:-1] if every == 1 else period}",
    }


def _crontab_periodic(
    *,
    minute: str = "0",
    hour: str = "0",
    day_of_month: str = "*",
    month_of_year: str = "*",
    day_of_week: str = "*",
    timezone: str = "Europe/Berlin",
    enabled: bool = True,
    task_id: int = _INVENTORY_SYNC_PERIODIC_ID,
    syncer: str | None = None,
) -> dict:
    """Build a fake crontab-mode inventory-sync periodic-task JSON row."""
    return {
        "id": task_id,
        "name": "inventory-sync",
        "task": "inventory-sync",
        "start_time": None,
        "enabled": enabled,
        "description": "",
        "execute_request": _execute_request_for(syncer),
        "interval": None,
        "crontab": {
            "minute": minute,
            "hour": hour,
            "day_of_month": day_of_month,
            "month_of_year": month_of_year,
            "day_of_week": day_of_week,
            "timezone": timezone,
        },
        "last_run_at": None,
        "total_run_count": 0,
        "date_changed": None,
        "next_run_at": None,
        "period": (f"{minute} {hour} {day_of_month} {month_of_year} {day_of_week}"),
    }


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_renders_no_schedule_state(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """Render the no-schedule state when the periodic-tasks API returns no rows."""
    mock_task_api_dep.get.return_value = []
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert "No schedule configured" in body
    assert "Attach a schedule" in body
    assert 'action="http://testserver/inventory/schedule/"' in body


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_renders_interval_schedule_enabled(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """Render the interval-mode schedule with Disable, Edit, and Clear actions."""
    mock_task_api_dep.get.return_value = [_interval_periodic()]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert "every 5 minutes" in body
    assert "Disable" in body
    assert "Edit Schedule" in body
    assert "Clear Schedule" in body
    assert f"/periodic/{_INVENTORY_SYNC_PERIODIC_ID}/update" in body
    assert f"/periodic/{_INVENTORY_SYNC_PERIODIC_ID}/delete" in body
    assert 'name="enabled" value="false"' in body


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_renders_interval_schedule_disabled(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """Render the disabled state with an Enable toggle and a "(disabled)" marker."""
    mock_task_api_dep.get.return_value = [_interval_periodic(enabled=False)]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert "(disabled)" in body
    assert "Enable" in body
    assert 'name="enabled" value="true"' in body


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_renders_crontab_schedule(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """Render a crontab-mode schedule with the cron expression and timezone."""
    mock_task_api_dep.get.return_value = [
        _crontab_periodic(
            minute="0", hour="0", day_of_month="*", month_of_year="*", day_of_week="*"
        )
    ]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert "0 0 * * *" in body
    assert "Europe/Berlin" in body
    assert 'value="crontab"' in body


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_renders_persisted_start_time(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """Surface ``start_time`` on the schedule block when the persisted row has it set."""
    schedule = _interval_periodic()
    schedule["start_time"] = "2026-05-01T09:00:00+00:00"
    mock_task_api_dep.get.return_value = [schedule]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert "Starts at:" in body
    assert "2026-05-01T09:00:00+00:00" in body


@pytest.mark.usefixtures("mock_sync_item_manager", "mock_get_username_mapping")
def test_node_list_includes_available_timezones_in_context(
    mocker, test_client, mock_inventory_api_dep, mock_task_api_dep, mock_syncers
):
    """Pass ``AVAILABLE_TIMEZONES`` through to the template context."""
    mock_task_api_dep.get.return_value = []
    template_spy = mocker.spy(templates, "TemplateResponse")
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    _, kwargs = template_spy.call_args
    assert kwargs["context"]["AVAILABLE_TIMEZONES"] == AVAILABLE_TIMEZONES


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_attach_form_uses_inventory_schedule_create_route(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """Render the attach form pointing at the inventory-specific create route."""
    mock_task_api_dep.get.return_value = []
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert 'action="http://testserver/inventory/schedule/"' in body
    assert 'name="task" value="inventory-sync"' not in body


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_pre_fills_form_for_existing_interval_schedule(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """Pre-fill the edit form's interval inputs from the existing schedule."""
    mock_task_api_dep.get.return_value = [_interval_periodic(every=15, period="hours")]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert 'name="interval_every"' in body
    assert 'value="15"' in body
    assert '<option value="hours" selected>' in body


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_pre_fills_form_for_existing_crontab_schedule(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """Pre-fill the edit form's cron inputs from the existing schedule."""
    mock_task_api_dep.get.return_value = [
        _crontab_periodic(
            minute="*/5",
            hour="*",
            day_of_month="*",
            month_of_year="*",
            day_of_week="*",
            timezone="America/New_York",
        )
    ]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert "*/5 * * * *" in body
    assert re.search(r'<option value="America/New_York"\s+selected\s*>', body)


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_renders_legacy_schedule_with_all_syncers_label(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """A row without ``execute_request`` renders with the "All syncers" label."""
    mock_task_api_dep.get.return_value = [_interval_periodic()]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert "All syncers" in body


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_renders_per_syncer_schedule_with_display_name(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """A schedule with a known syncer renders the syncer's display name."""
    mock_task_api_dep.get.return_value = [_interval_periodic(syncer=PMM_STUB_NAME)]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert "<strong>StubPMM</strong>" in body
    assert "All syncers" not in body.split("Attach a schedule")[0]


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_renders_two_schedules_with_distinct_actions(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """Two schedules render as two rows whose update/delete URLs differ."""
    mock_task_api_dep.get.return_value = [
        _interval_periodic(task_id=11),
        _interval_periodic(task_id=22, syncer=PMM_STUB_NAME),
    ]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert "/periodic/11/update" in body
    assert "/periodic/11/delete" in body
    assert "/periodic/22/update" in body
    assert "/periodic/22/delete" in body
    assert 'data-schedule-id="11"' in body
    assert 'data-schedule-id="22"' in body


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_renders_unknown_syncer_label_falls_through(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """A row referencing a syncer that is no longer configured renders without crashing."""
    mock_task_api_dep.get.return_value = [
        _interval_periodic(syncer="app.sep.sync.syncers.gone.RemovedSyncer")
    ]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert "RemovedSyncer" in body


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_renders_per_row_disabled_marker(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """The ``(disabled)`` marker appears only on the disabled row."""
    mock_task_api_dep.get.return_value = [
        _interval_periodic(task_id=11, enabled=True),
        _interval_periodic(task_id=22, enabled=False, syncer=PMM_STUB_NAME),
    ]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert body.count("(disabled)") == 1


@pytest.mark.usefixtures(
    "mock_sync_item_manager", "mock_get_username_mapping", "mock_syncers"
)
def test_node_list_attach_form_includes_syncer_radio_options(
    test_client, mock_inventory_api_dep, mock_task_api_dep
):
    """Attach form exposes a radio for "All syncers" plus one per available syncer."""
    mock_task_api_dep.get.return_value = []
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert 'type="radio" name="syncer" value=""' in body
    assert f'value="{PMM_STUB_NAME}"' in body
    assert f'value="{MYSQL_STUB_NAME}"' in body


@pytest.mark.asyncio
async def test_schedule_create_attach_with_syncer_succeeds(
    async_test_client, mock_syncers, mock_task_api_dep
):
    """Posting a syncer attaches a schedule with the syncer in execute_request.meta."""
    response = await async_test_client.post(
        "/inventory/schedule/",
        data={
            "syncer": PMM_STUB_NAME,
            "schedule_mode": "interval",
            "interval_every": "5",
            "interval_period": "minutes",
        },
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_awaited_once_with(
        "/inventory-sync/periodic/",
        json={
            "task": "inventory-sync",
            "interval": {"every": 5, "period": "minutes"},
            "execute_request": {"meta": {"syncer": PMM_STUB_NAME}},
        },
    )


@pytest.mark.asyncio
async def test_schedule_create_attach_all_syncers_succeeds(
    async_test_client, mock_syncers, mock_task_api_dep
):
    """An empty syncer field omits ``execute_request`` from the payload."""
    response = await async_test_client.post(
        "/inventory/schedule/",
        data={
            "syncer": "",
            "schedule_mode": "interval",
            "interval_every": "10",
            "interval_period": "minutes",
        },
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_awaited_once_with(
        "/inventory-sync/periodic/",
        json={
            "task": "inventory-sync",
            "interval": {"every": 10, "period": "minutes"},
        },
    )


@pytest.mark.asyncio
async def test_schedule_create_attach_with_crontab_succeeds(
    async_test_client, mock_syncers, mock_task_api_dep
):
    """Crontab variant posts a parsed crontab dict to the Tasks API."""
    response = await async_test_client.post(
        "/inventory/schedule/",
        data={
            "syncer": PMM_STUB_NAME,
            "schedule_mode": "crontab",
            "cron_expression": "0 0 * * *",
            "cron_timezone": "UTC",
        },
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_awaited_once_with(
        "/inventory-sync/periodic/",
        json={
            "task": "inventory-sync",
            "crontab": {
                "timezone": "UTC",
                "minute": "0",
                "hour": "0",
                "day_of_month": "*",
                "month_of_year": "*",
                "day_of_week": "*",
            },
            "execute_request": {"meta": {"syncer": PMM_STUB_NAME}},
        },
    )


@pytest.mark.asyncio
async def test_schedule_create_attach_with_unknown_syncer_skips_post(
    async_test_client, mock_syncers, mock_task_api_dep
):
    """An unknown syncer value redirects with a flash and does not call the Tasks API."""
    response = await async_test_client.post(
        "/inventory/schedule/",
        data={
            "syncer": "app.fake.UnknownSyncer",
            "schedule_mode": "interval",
            "interval_every": "5",
            "interval_period": "minutes",
        },
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_create_attach_with_both_modes_skips_post(
    async_test_client, mock_syncers, mock_task_api_dep
):
    """Submitting both interval and crontab fields fails fast without POSTing."""
    response = await async_test_client.post(
        "/inventory/schedule/",
        data={
            "syncer": "",
            "schedule_mode": "interval",
            "interval_every": "5",
            "interval_period": "minutes",
            "cron_expression": "0 0 * * *",
            "cron_timezone": "UTC",
        },
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_create_attach_with_neither_mode_skips_post(
    async_test_client, mock_syncers, mock_task_api_dep
):
    """Submitting neither interval nor crontab fields fails fast without POSTing."""
    response = await async_test_client.post(
        "/inventory/schedule/",
        data={"syncer": ""},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_create_blocked_when_token_unset(
    async_test_client, mocker, mock_syncers, mock_task_api_dep
):
    """Reject schedule creation when ``SEP_INTERNAL_TOKEN`` is unset."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", None)
    response = await async_test_client.post(
        "/inventory/schedule/",
        data={
            "syncer": "",
            "schedule_mode": "interval",
            "interval_every": "5",
            "interval_period": "minutes",
        },
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_create_blocked_when_token_empty(
    async_test_client, mocker, mock_syncers, mock_task_api_dep
):
    """Reject schedule creation when ``SEP_INTERNAL_TOKEN`` is an empty string."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(""))
    response = await async_test_client.post(
        "/inventory/schedule/",
        data={
            "syncer": "",
            "schedule_mode": "interval",
            "interval_every": "5",
            "interval_period": "minutes",
        },
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_not_awaited()


@pytest.mark.usefixtures("mock_sync_item_manager", "mock_get_username_mapping")
def test_node_list_context_scheduled_sync_enabled_when_token_set(
    mocker, test_client, mock_inventory_api_dep, mock_task_api_dep, mock_syncers
):
    """Pass ``scheduled_sync_enabled=True`` to the template when the token is set."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr("ok"))
    mock_task_api_dep.get.return_value = []
    template_spy = mocker.spy(templates, "TemplateResponse")
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    _, kwargs = template_spy.call_args
    assert kwargs["context"]["scheduled_sync_enabled"] is True
    body = _compact(response.text)
    assert "Attach a schedule" in body
    assert "schedule-disabled-notice" not in body


@pytest.mark.usefixtures("mock_sync_item_manager", "mock_get_username_mapping")
def test_node_list_context_scheduled_sync_disabled_when_token_unset(
    mocker, test_client, mock_inventory_api_dep, mock_task_api_dep, mock_syncers
):
    """Pass ``scheduled_sync_enabled=False`` and render the notice when token unset."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", None)
    mock_task_api_dep.get.return_value = []
    template_spy = mocker.spy(templates, "TemplateResponse")
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    _, kwargs = template_spy.call_args
    assert kwargs["context"]["scheduled_sync_enabled"] is False
    body = _compact(response.text)
    assert "schedule-disabled-notice" in body
    assert "SEP_INTERNAL_TOKEN" in body
    assert "Attach a schedule" not in body


@pytest.mark.usefixtures("mock_sync_item_manager", "mock_get_username_mapping")
def test_node_list_renders_per_row_chip_when_token_unset(
    mocker, test_client, mock_inventory_api_dep, mock_task_api_dep, mock_syncers
):
    """Render the "(will not run)" chip on existing schedule rows when token unset."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", None)
    mock_task_api_dep.get.return_value = [_interval_periodic()]
    response = test_client.get("/inventory/")
    assert response.status_code == status.HTTP_200_OK
    body = _compact(response.text)
    assert "schedule-stale-warning" in body
    assert "will not run" in body


def test_schedule_post_is_omitted_from_openapi(test_client):
    """Verify ``POST /inventory/schedule/`` is excluded from the OpenAPI schema."""
    response = test_client.get("/openapi.json")
    assert response.status_code == status.HTTP_200_OK
    schema = response.json()
    schedule_ops = schema["paths"].get("/inventory/schedule/", {})
    assert "post" not in schedule_ops
