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

"""Define tests for the inventory plugin JSON API routes under ``/api/apps/inventory/``.

Path mapping, entity validation, list unwrapping, and query forwarding are
implemented in ``app.sep.apps.inventory.deps``; see
``tests/app/sep/apps/inventory/test_deps.py`` for direct unit coverage.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from pydantic import SecretStr

from app.core.config import settings
from app.core.pagination import DEFAULT_PAGINATION_OFFSET, MAX_PAGINATION_LIMIT
from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.inventory.deps import (
    get_syncers,
    INVENTORY_PLUGIN_ENTITY_NAMES,
)
from app.sep.crud import SyncItemManager
from app.sep.deps import (
    BEARER_REQUIRED_DETAIL,
    get_created_service,
    get_current_user,
    get_tasks_api,
)
from app.sep.main import sep_app
from app.sep.models import SyncInventoryEntityTypeEnum
from tests.app.factories import CreatedNodeFactory, CreatedServiceFactory
from tests.app.sep.apps.inventory.conftest import no_syncers, PMM_STUB_NAME

_EXPECTED_SCHEMA_ENTITY_COUNT = len(INVENTORY_PLUGIN_ENTITY_NAMES)
_MYSQL_PORT = 3306
_TASK_HISTORY_ID = 42
_ENVELOPE_TOTAL = 7
_REQUEST_OFFSET = 2
_REQUEST_LIMIT = 5
_UPSTREAM_OFFSET = 99
_UPSTREAM_LIMIT = 1
_CREATE_SERVICE_TEST_NODE_ID = 7


class TestInventoryResponseModelsInOpenAPI:
    """Ensure new endpoints expose typed Pydantic models in the OpenAPI schema."""

    def test_plugin_tasks_response_schema_is_defined(self, test_client):
        """Ensure the app-namespaced PluginTaskResponse is a named schema in the OpenAPI spec."""
        response = test_client.get("/openapi.json")
        assert response.status_code == status.HTTP_200_OK
        schemas = response.json().get("components", {}).get("schemas", {})
        assert "inventory__PluginTaskResponse" in schemas

    def test_available_syncers_response_schema_is_defined(self, test_client):
        """Ensure the app-namespaced AvailableSyncer is a named schema in the OpenAPI spec."""
        response = test_client.get("/openapi.json")
        assert response.status_code == status.HTTP_200_OK
        schemas = response.json().get("components", {}).get("schemas", {})
        assert "inventory__AvailableSyncer" in schemas

    def test_plugin_tasks_openapi_response_references_model(self, test_client):
        """Ensure GET /api/apps/inventory/ response body references PluginTaskResponse."""
        response = test_client.get("/openapi.json")
        spec = response.json()
        get_op = spec["paths"]["/api/apps/inventory/"]["get"]
        response_schema = get_op["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert response_schema.get("type") == "array"
        ref = response_schema.get("items", {}).get("$ref", "")
        assert "PluginTaskResponse" in ref

    def test_available_syncers_openapi_response_references_model(self, test_client):
        """Ensure GET /api/apps/inventory/available-syncers/ response references AvailableSyncer."""
        response = test_client.get("/openapi.json")
        spec = response.json()
        get_op = spec["paths"]["/api/apps/inventory/available-syncers/"]["get"]
        response_schema = get_op["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert response_schema.get("type") == "array"
        ref = response_schema.get("items", {}).get("$ref", "")
        assert "AvailableSyncer" in ref


class TestInventorySchemaEndpoint:
    """Tests for GET /api/apps/inventory/schema."""

    def test_schema_returns_200(self, test_client):
        """Ensure the schema endpoint returns HTTP 200 with the expected plugin body."""
        response = test_client.get("/api/apps/inventory/schema")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "inventory"
        assert len(body["entities"]) == _EXPECTED_SCHEMA_ENTITY_COUNT


class TestInventoryGateway:
    """Tests for inventory CRUD proxy routes under ``/api/apps/inventory/``."""

    def test_list_nodes_echoes_request_window_and_preserves_total(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure the envelope echoes the request window and keeps the upstream total.

        The response ``offset``/``limit`` reflect what the client asked for, not
        whatever the upstream happened to return; only ``total`` is proxied.
        """
        mock_inventory_api_dep.get.return_value = {
            "items": [{"id": 1, "name": "n"}],
            "total": _ENVELOPE_TOTAL,
            "offset": _UPSTREAM_OFFSET,
            "limit": _UPSTREAM_LIMIT,
        }
        response = test_client.get(
            "/api/apps/inventory/nodes/",
            params={"offset": _REQUEST_OFFSET, "limit": _REQUEST_LIMIT},
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["items"] == [{"id": 1, "name": "n"}]
        assert body["total"] == _ENVELOPE_TOTAL
        assert body["offset"] == _REQUEST_OFFSET
        assert body["limit"] == _REQUEST_LIMIT
        mock_inventory_api_dep.get.assert_awaited_once_with(
            "/nodes/",
            params={"offset": _REQUEST_OFFSET, "limit": _REQUEST_LIMIT},
        )

    def test_list_forwards_validated_pagination_and_preserves_filters(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure entity filters survive while validated offset/limit are forwarded."""
        mock_inventory_api_dep.get.return_value = {"items": [], "total": 0}
        response = test_client.get(
            "/api/apps/inventory/nodes/",
            params={"name": "db1", "limit": _REQUEST_LIMIT},
        )
        assert response.status_code == status.HTTP_200_OK
        mock_inventory_api_dep.get.assert_awaited_once_with(
            "/nodes/",
            params={
                "name": "db1",
                "offset": DEFAULT_PAGINATION_OFFSET,
                "limit": _REQUEST_LIMIT,
            },
        )

    def test_list_rejects_out_of_bounds_limit_with_422(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure a limit above ``MAX_PAGINATION_LIMIT`` is rejected before any upstream call."""
        response = test_client.get(
            "/api/apps/inventory/nodes/",
            params={"limit": MAX_PAGINATION_LIMIT + 1},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_inventory_api_dep.get.assert_not_called()

    def test_unknown_entity_404(self, test_client, mock_inventory_api_dep):
        """Ensure GET on an unknown entity segment returns HTTP 404."""
        response = test_client.get("/api/apps/inventory/unknown/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_service_forwards_to_node_services(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure POST ``/api/apps/inventory/services/`` maps to ``/nodes/{node_id}/services/`` on inventory."""
        mock_inventory_api_dep.post.return_value = {"id": 2, "name": "svc"}
        response = test_client.post(
            "/api/apps/inventory/services/",
            json={
                "node_id": _CREATE_SERVICE_TEST_NODE_ID,
                "name": "db",
                "type": ServiceTypeEnum.MYSQL.value,
            },
        )
        assert response.status_code == status.HTTP_200_OK
        mock_inventory_api_dep.post.assert_awaited_once()
        call_args = mock_inventory_api_dep.post.await_args
        assert call_args[0][0] == f"/nodes/{_CREATE_SERVICE_TEST_NODE_ID}/services/"
        assert call_args[1]["json"]["node_id"] == _CREATE_SERVICE_TEST_NODE_ID

    def test_create_service_invalid_node_id_returns_422(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure non-numeric ``node_id`` returns HTTP 422 and does not call inventory."""
        response = test_client.post(
            "/api/apps/inventory/services/",
            json={
                "node_id": "abc",
                "name": "db",
                "type": ServiceTypeEnum.MYSQL.value,
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_inventory_api_dep.post.assert_not_called()

    def test_create_schema_requires_service_id(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure POST ``/api/apps/inventory/schemas/`` without ``service_id`` returns HTTP 422."""
        response = test_client.post(
            "/api/apps/inventory/schemas/",
            json={"name": "db1"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.parametrize(
        ("raw_content", "content_type"),
        [
            (b"", "application/json"),
            (b"{not-json", "application/json"),
            (b"\xff", "application/json; charset=utf-8"),
        ],
    )
    def test_post_rejects_empty_or_malformed_json_body_with_422(
        self,
        test_client,
        mock_inventory_api_dep,
        raw_content: bytes,
        content_type: str,
    ) -> None:
        """Ensure invalid JSON on POST returns HTTP 422 and does not call inventory."""
        response = test_client.post(
            "/api/apps/inventory/nodes/",
            content=raw_content,
            headers={"Content-Type": content_type},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert response.json()["detail"] == "JSON object body required"
        mock_inventory_api_dep.post.assert_not_called()

    def test_delete_returns_204(self, test_client, mock_inventory_api_dep):
        """Ensure DELETE ``/api/apps/inventory/nodes/{id}`` returns HTTP 204 with an empty body."""
        mock_inventory_api_dep.delete.return_value = None
        response = test_client.delete("/api/apps/inventory/nodes/3")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""
        mock_inventory_api_dep.delete.assert_awaited_once_with("/nodes/3")

    @pytest.mark.parametrize(
        ("entity", "item_id", "inventory_path"),
        [
            ("nodes", 3, "/nodes/3"),
            ("services", 9, "/services/9"),
            ("schemas", 11, "/schemas/11"),
            ("tables", 42, "/tables/42"),
        ],
    )
    def test_get_entity_detail_forwards_inventory_path(
        self,
        test_client,
        mock_inventory_api_dep,
        entity: str,
        item_id: int,
        inventory_path: str,
    ):
        """Ensure GET ``…/{entity}/{id}`` proxies to the inventory service detail path."""
        payload = {"id": item_id, "name": "x"}
        mock_inventory_api_dep.get.return_value = payload
        response = test_client.get(f"/api/apps/inventory/{entity}/{item_id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload
        mock_inventory_api_dep.get.assert_awaited_once_with(inventory_path)

    @pytest.mark.parametrize(
        ("entity", "item_id", "inventory_path"),
        [
            ("nodes", 3, "/nodes/3"),
            ("services", 9, "/services/9"),
            ("schemas", 11, "/schemas/11"),
            ("tables", 42, "/tables/42"),
        ],
    )
    def test_put_entity_detail_forwards_inventory_path_and_body(
        self,
        test_client,
        mock_inventory_api_dep,
        entity: str,
        item_id: int,
        inventory_path: str,
    ):
        """Ensure PUT ``…/{entity}/{id}`` forwards JSON to the inventory service detail path."""
        request_body = {"name": "updated"}
        updated = {"id": item_id, **request_body}
        mock_inventory_api_dep.put.return_value = updated
        response = test_client.put(
            f"/api/apps/inventory/{entity}/{item_id}",
            json=request_body,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == updated
        mock_inventory_api_dep.put.assert_awaited_once_with(
            inventory_path,
            json=request_body,
        )

    def test_get_unknown_entity_detail_returns_404(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure GET on an unknown entity segment returns HTTP 404 before inventory."""
        response = test_client.get("/api/apps/inventory/unknown/1")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_inventory_api_dep.get.assert_not_called()


class TestInventorySchemaCapabilities:
    """Tests for capabilities flags on the inventory plugin schema."""

    def test_schema_has_scheduling_capability(self, test_client):
        """Ensure the inventory schema advertises ``scheduling=True``."""
        response = test_client.get("/api/apps/inventory/schema")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["capabilities"]["scheduling"] is True


class TestInventoryPluginTasksEndpoint:
    """Tests for GET /api/apps/inventory/ (plugin task discovery)."""

    def test_returns_200_with_inventory_sync_task(self, test_client):
        """Ensure endpoint returns 200 and includes the inventory-sync task."""
        response = test_client.get("/api/apps/inventory/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert isinstance(body, list)
        assert any(t["name"] == "inventory-sync" for t in body)

    def test_response_shape_matches_use_plugin_tasks_contract(self, test_client):
        """Ensure every item has at minimum a ``name`` key for the React hook."""
        response = test_client.get("/api/apps/inventory/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        for task in body:
            assert "name" in task

    def test_does_not_clash_with_entity_wildcard(self, test_client):
        """Ensure ``GET /`` resolves to the tasks handler, not the ``/{entity}/`` wildcard."""
        response = test_client.get("/api/apps/inventory/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert isinstance(body, list)


class TestInventoryAvailableSyncersEndpoint:
    """Tests for GET /api/apps/inventory/available-syncers/."""

    def test_returns_200_with_syncers_list(self, test_client, mock_syncers_dep):
        """Ensure endpoint returns 200 and a list."""
        response = test_client.get("/api/apps/inventory/available-syncers/")
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.json(), list)

    def test_filters_to_can_sync_inventory_only(self, test_client, mock_syncers_dep):
        """Ensure only syncers where ``can_sync_inventory()`` is True are returned."""
        response = test_client.get("/api/apps/inventory/available-syncers/")
        body = response.json()
        assert len(body) == 1

    def test_response_items_have_name_and_display_name(
        self, test_client, mock_syncers_dep
    ):
        """Ensure each syncer item carries ``name`` and ``display_name``."""
        response = test_client.get("/api/apps/inventory/available-syncers/")
        for item in response.json():
            assert "name" in item
            assert "display_name" in item

    def test_display_name_and_name_are_strings(self, test_client, mock_syncers_dep):
        """Ensure ``name`` and ``display_name`` are plain strings, not callables or objects."""
        response = test_client.get("/api/apps/inventory/available-syncers/")
        for item in response.json():
            assert isinstance(item["name"], str)
            assert isinstance(item["display_name"], str)

    def test_no_matching_syncers_returns_empty_list(self, test_client):
        """When all syncers return ``can_sync_inventory=False``, endpoint returns ``[]``."""

        class _NoSync:
            def can_sync_inventory(self) -> bool:
                return False

        sep_app.dependency_overrides[get_syncers] = lambda: [_NoSync()]
        try:
            response = test_client.get("/api/apps/inventory/available-syncers/")
            assert response.status_code == status.HTTP_200_OK
            assert response.json() == []
        finally:
            sep_app.dependency_overrides.pop(get_syncers, None)

    def test_syncers_dep_error_surfaces_500(self, test_client):
        """If ``get_syncers`` raises (e.g. bad config), the endpoint returns 500."""

        def _broken():
            raise RuntimeError("broken syncer import")

        sep_app.dependency_overrides[get_syncers] = _broken
        try:
            response = test_client.get("/api/apps/inventory/available-syncers/")
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        finally:
            sep_app.dependency_overrides.pop(get_syncers, None)

    def test_does_not_clash_with_entity_wildcard(self, test_client, mock_syncers_dep):
        """Ensure ``GET /available-syncers/`` does not fall through to ``/{entity}/`` wildcard."""
        response = test_client.get("/api/apps/inventory/available-syncers/")
        assert response.status_code == status.HTTP_200_OK


class TestInventoryNewRoutesAuthentication:
    """Ensure new plugin discovery routes enforce API authentication."""

    def test_plugin_tasks_rejects_unauthenticated(self, unauthenticated_client):
        """``GET /api/apps/inventory/`` must return 401 without a valid token."""
        response = unauthenticated_client.get("/api/apps/inventory/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_available_syncers_rejects_unauthenticated(self, unauthenticated_client):
        """``GET /api/apps/inventory/available-syncers/`` must return 401 without a valid token."""
        response = unauthenticated_client.get("/api/apps/inventory/available-syncers/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestInventoryBearerGate:
    """Cover Bearer-gate behavior on inventory JSON mutations."""

    def test_cookie_only_sync_post_returns_401(
        self, api_admin_client_no_bearer, mock_run_sync_funcs
    ):
        """Cookie-auth POST without Bearer header is 401'd by the framework gate."""
        response = api_admin_client_no_bearer.post("/api/apps/inventory/sync/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL
        mock_run_sync_funcs["inventory"].assert_not_called()

    @pytest.mark.parametrize(
        ("method", "path", "json_body"),
        [
            (
                "POST",
                "/api/apps/inventory/services/",
                {"node_id": 1, "name": "db", "type": "mysql"},
            ),
            ("PUT", "/api/apps/inventory/nodes/3", {"name": "x"}),
            ("DELETE", "/api/apps/inventory/nodes/3", None),
        ],
    )
    def test_inventory_crud_mutations_are_gate_rejected(
        self,
        api_admin_client_no_bearer,
        mock_inventory_api_dep,
        mock_run_sync_funcs,
        method: str,
        path: str,
        json_body: dict | None,
    ) -> None:
        """Every CRUD mutation under inventory 401s before any upstream call.

        Coverage matrix: POST (create), PUT (update), DELETE (destroy) all
        share the same gate. The inventory API mock must remain untouched.
        """
        kwargs = {"json": json_body} if json_body is not None else {}
        response = api_admin_client_no_bearer.request(method, path, **kwargs)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL
        mock_inventory_api_dep.post.assert_not_called()
        mock_inventory_api_dep.put.assert_not_called()
        mock_inventory_api_dep.delete.assert_not_called()
        mock_run_sync_funcs["inventory"].assert_not_called()


class TestInventorySyncTrigger:
    """Tests for POST ``/api/apps/inventory/sync/``.

    Mirrors the Jinja2 contract at ``app/sep/apps/inventory/routes.py``
    ``POST /sync/`` but delivers a JSON-API surface: a 202 on accepted
    triggers and a 400 on unknown/inapplicable syncer names. The
    ``run_inventory_sync`` background task is never actually executed; it
    is patched to an ``AsyncMock`` so tests can assert what arguments
    ``BackgroundTasks.add_task`` would have scheduled.
    """

    def test_no_body_schedules_sync_all(
        self, test_client, mock_syncers, mock_run_sync_funcs
    ):
        """POST with no body returns 202 and schedules every configured syncer."""
        response = test_client.post("/api/apps/inventory/sync/")
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.content == b""
        mock_run_sync_funcs["inventory"].assert_awaited_once()
        args = mock_run_sync_funcs["inventory"].await_args.args
        assert list(args[1:]) == mock_syncers

    def test_sync_uses_internal_token(
        self, test_client, mock_syncers, mock_run_sync_funcs, mocker
    ):
        """The API sync background task is scheduled with the internal token."""
        mocker.patch.object(
            settings, "SEP_INTERNAL_TOKEN", SecretStr("api-internal-token")
        )
        response = test_client.post("/api/apps/inventory/sync/")
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_run_sync_funcs["inventory"].assert_awaited_once()
        args = mock_run_sync_funcs["inventory"].await_args.args
        assert args[0] == "api-internal-token"

    def test_empty_object_body_schedules_sync_all(
        self, test_client, mock_syncers, mock_run_sync_funcs
    ):
        """POST ``{}`` returns 202 and schedules every configured syncer."""
        response = test_client.post("/api/apps/inventory/sync/", json={})
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_run_sync_funcs["inventory"].assert_awaited_once()
        args = mock_run_sync_funcs["inventory"].await_args.args
        assert list(args[1:]) == mock_syncers

    def test_null_syncer_schedules_sync_all(
        self, test_client, mock_syncers, mock_run_sync_funcs
    ):
        """POST ``{"syncer": null}`` returns 202 and schedules every configured syncer."""
        response = test_client.post(
            "/api/apps/inventory/sync/",
            json={"syncer": None},
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_run_sync_funcs["inventory"].assert_awaited_once()
        args = mock_run_sync_funcs["inventory"].await_args.args
        assert list(args[1:]) == mock_syncers

    def test_empty_syncer_string_schedules_sync_all(
        self, test_client, mock_syncers, mock_run_sync_funcs
    ):
        """POST ``{"syncer": ""}`` matches the Jinja2 contract: sync-all path."""
        response = test_client.post(
            "/api/apps/inventory/sync/",
            json={"syncer": ""},
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_run_sync_funcs["inventory"].assert_awaited_once()
        args = mock_run_sync_funcs["inventory"].await_args.args
        assert list(args[1:]) == mock_syncers

    def test_named_syncer_schedules_only_that_syncer(
        self, test_client, mock_syncers, mock_run_sync_funcs
    ):
        """POST ``{"syncer": "<name>"}`` schedules only the matching syncer."""
        response = test_client.post(
            "/api/apps/inventory/sync/",
            json={"syncer": PMM_STUB_NAME},
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_run_sync_funcs["inventory"].assert_awaited_once()
        args = mock_run_sync_funcs["inventory"].await_args.args
        assert list(args[1:]) == [mock_syncers[0]]

    def test_unknown_syncer_returns_400_and_does_not_schedule(
        self, test_client, mock_syncers, mock_run_sync_funcs
    ):
        """A syncer name that matches no configured syncer yields HTTP 400."""
        response = test_client.post(
            "/api/apps/inventory/sync/",
            json={"syncer": "not.a.real.Syncer"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_run_sync_funcs["inventory"].assert_not_awaited()

    def test_incapable_syncer_returns_400(
        self, test_client, mock_syncers, mock_run_sync_funcs, mocker
    ):
        """A syncer matching by name but failing the capability check yields 400."""
        mocker.patch.object(
            type(mock_syncers[0]), "can_sync_inventory", return_value=False
        )
        response = test_client.post(
            "/api/apps/inventory/sync/",
            json={"syncer": PMM_STUB_NAME},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_run_sync_funcs["inventory"].assert_not_awaited()

    def test_no_syncers_configured_with_named_returns_400(
        self, test_client, mock_run_sync_funcs
    ):
        """With zero configured syncers, a named target still 400s."""
        sep_app.dependency_overrides[get_syncers] = no_syncers
        try:
            response = test_client.post(
                "/api/apps/inventory/sync/",
                json={"syncer": PMM_STUB_NAME},
            )
        finally:
            sep_app.dependency_overrides.pop(get_syncers, None)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_run_sync_funcs["inventory"].assert_not_awaited()

    def test_no_syncers_configured_sync_all_still_202(
        self, test_client, mock_run_sync_funcs
    ):
        """With zero configured syncers, sync-all returns 202 (matches Jinja2)."""
        sep_app.dependency_overrides[get_syncers] = no_syncers
        try:
            response = test_client.post("/api/apps/inventory/sync/")
        finally:
            sep_app.dependency_overrides.pop(get_syncers, None)
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_run_sync_funcs["inventory"].assert_awaited_once()
        args = mock_run_sync_funcs["inventory"].await_args.args
        assert list(args[1:]) == []

    def test_wrong_type_for_syncer_returns_422(
        self, test_client, mock_syncers, mock_run_sync_funcs
    ):
        """A non-string ``syncer`` value is rejected by Pydantic with 422."""
        response = test_client.post(
            "/api/apps/inventory/sync/",
            json={"syncer": 123},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_run_sync_funcs["inventory"].assert_not_awaited()

    def test_extra_fields_rejected_with_422(
        self, test_client, mock_syncers, mock_run_sync_funcs
    ):
        """Unknown body fields are rejected so client typos cannot silently sync-all."""
        response = test_client.post(
            "/api/apps/inventory/sync/",
            json={"syncer": None, "extra": "x"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_run_sync_funcs["inventory"].assert_not_awaited()

    def test_malformed_json_returns_422(
        self, test_client, mock_syncers, mock_run_sync_funcs
    ):
        """A malformed JSON body returns 422 (FastAPI default) and does not schedule."""
        response = test_client.post(
            "/api/apps/inventory/sync/",
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_run_sync_funcs["inventory"].assert_not_awaited()

    def test_requires_authentication(self, unauthenticated_client, mock_run_sync_funcs):
        """Without API auth the gateway returns 401."""
        response = unauthenticated_client.post("/api/apps/inventory/sync/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        mock_run_sync_funcs["inventory"].assert_not_awaited()


class TestInventorySyncStatus:
    """Tests for GET ``/api/apps/inventory/sync/status/``."""

    def test_returns_false_when_idle(self, test_client, mocker):
        """Returns ``{"is_running": false}`` when ``SyncItemManager`` reports idle."""
        spy = mocker.patch.object(
            SyncItemManager, "sync_is_running", new=AsyncMock(return_value=False)
        )
        response = test_client.get("/api/apps/inventory/sync/status/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"is_running": False}
        # Regression guard: this endpoint reports INVENTORY status, not
        # NODE/SERVICE/SCHEMA — copy-paste bugs would change the enum.
        assert spy.await_args.args[1] == SyncInventoryEntityTypeEnum.INVENTORY

    def test_returns_true_when_running(self, test_client, mocker):
        """Returns ``{"is_running": true}`` when ``SyncItemManager`` reports active."""
        mocker.patch.object(
            SyncItemManager, "sync_is_running", new=AsyncMock(return_value=True)
        )
        response = test_client.get("/api/apps/inventory/sync/status/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"is_running": True}

    def test_requires_authentication(self, unauthenticated_client):
        """Without API auth the status endpoint returns 401."""
        response = unauthenticated_client.get("/api/apps/inventory/sync/status/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestInventorySystemObservation:
    """Tests for the read-only system-observation proxy routes.

    Cover both the host (node) and service endpoints across the
    facts-present (200) and not-collected (404) paths. The 404 originates in
    the inventory sub-app and must propagate unchanged so the React panel can
    render its empty state instead of an error toast.
    """

    @pytest.mark.parametrize(
        ("url", "inventory_path", "payload"),
        [
            (
                "/api/apps/inventory/nodes/3/system-observation",
                "/nodes/3/system-observation",
                {
                    # Host observation shape: os_version, installed_packages,
                    # config; no db_engine_version.
                    "os_version": "Ubuntu 22.04",
                    "installed_packages": {"openssl": "3.0.2"},
                    "config": {"max_connections": 100},
                    "observed_at": "2026-06-01T12:00:00Z",
                },
            ),
            (
                "/api/apps/inventory/services/9/system-observation",
                "/services/9/system-observation",
                {
                    # Service observation shape: db_engine_version only.
                    "db_engine_version": "8.0.36",
                    "observed_at": "2026-06-01T12:00:00Z",
                },
            ),
        ],
    )
    def test_system_observation_present_returns_200(
        self,
        test_client,
        mock_inventory_api_dep,
        url: str,
        inventory_path: str,
        payload: dict,
    ):
        """Ensure a present observation proxies through with HTTP 200 and forwards the sub-resource path."""
        mock_inventory_api_dep.get.return_value = payload
        response = test_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload
        mock_inventory_api_dep.get.assert_awaited_once_with(inventory_path)

    @pytest.mark.parametrize(
        "url",
        [
            "/api/apps/inventory/nodes/3/system-observation",
            "/api/apps/inventory/services/9/system-observation",
        ],
    )
    def test_system_observation_not_collected_passes_through_404(
        self,
        test_client,
        mock_inventory_api_dep,
        url: str,
    ):
        """Ensure an upstream 404 (not collected yet) propagates as HTTP 404."""
        mock_inventory_api_dep.get.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No system observation",
        )
        response = test_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize(
        "url",
        [
            "/api/apps/inventory/nodes/3/system-observation",
            "/api/apps/inventory/services/9/system-observation",
        ],
    )
    def test_system_observation_requires_authentication(
        self,
        unauthenticated_client,
        url: str,
    ):
        """Without API auth the system-observation endpoints return 401."""
        response = unauthenticated_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_openapi_schema_is_named_model_not_inline_dict(self):
        """The 200 response schema must reference a named model, not an inline dict.

        ``dict[str, bool]`` generates a free-form ``additionalProperties``
        schema; ``InventorySyncStatusResponse`` generates a ``$ref`` to a named
        component. The React client's generated hooks depend on a stable schema
        name, so this assertion guards against regression to the untyped form.
        """
        prior_schema = sep_app.openapi_schema
        sep_app.openapi_schema = None
        try:
            openapi = sep_app.openapi()
            response_schema = openapi["paths"]["/api/apps/inventory/sync/status/"][
                "get"
            ]["responses"]["200"]["content"]["application/json"]["schema"]
            assert "$ref" in response_schema, (
                "Expected a $ref to InventorySyncStatusResponse; got inline schema. "
                "Change the return type annotation back to InventorySyncStatusResponse."
            )
        finally:
            sep_app.openapi_schema = prior_schema


class TestInventoryServiceCheckConnectivity:
    """Cover POST /api/apps/inventory/services/{service_id}/check-connectivity/."""

    @pytest.fixture(autouse=True)
    def _admin_identity(self, test_client, admin_user):
        """Resolve the API identity to an admin for the probe's own ``IsApiAdmin``.

        Declared after ``test_client`` so it replaces the non-admin identity that
        fixture installs; :meth:`test_non_admin_is_refused` opts out by
        re-installing the non-admin.
        """
        sep_app.dependency_overrides[get_current_user] = lambda: admin_user
        yield
        sep_app.dependency_overrides.pop(get_current_user, None)

    @pytest.fixture
    def created_node(self):
        """Return a fake inventory node."""
        return CreatedNodeFactory.build()

    @pytest.fixture
    def mysql_service(self, created_node):
        """Return a MySQL service attached to ``created_node`` with a port set."""
        service = CreatedServiceFactory.build(
            type=ServiceTypeEnum.MYSQL, port=_MYSQL_PORT
        )
        service.node = created_node
        return service

    @pytest.fixture
    def _mock_mysql_service_dep(self, mysql_service):
        """Resolve ``CreatedServiceDep`` to the MySQL service."""
        sep_app.dependency_overrides[get_created_service] = lambda: mysql_service
        yield
        sep_app.dependency_overrides.pop(get_created_service, None)

    @pytest.fixture
    def mock_tasks_api_dep(self, created_node) -> AsyncMock:
        """Mock ``TaskAPI`` with a host mapping that resolves ``created_node``."""
        mock = AsyncMock(spec=RemoteAPI)
        mock.get.return_value = {created_node.name: created_node.address}
        sep_app.dependency_overrides[get_tasks_api] = lambda: mock
        yield mock
        sep_app.dependency_overrides.pop(get_tasks_api, None)

    def _url(self, service) -> str:
        return f"/api/apps/inventory/services/{service.id}/check-connectivity/"

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_non_admin_is_refused(
        self, test_client, mysql_service, mock_tasks_api_dep, regular_user
    ):
        """Refuse a non-admin: the probe opens a connection with stored credentials.

        Its already-admin sibling is ``POST /api/sep/admin/connectivity-check/``,
        and the declaration is on the route rather than left to the router-level
        gate so the posture is readable where the route is defined.
        """
        sep_app.dependency_overrides[get_current_user] = lambda: regular_user

        response = test_client.post(self._url(mysql_service))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_successful_probe_returns_200(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Return HTTP 200 carrying the upstream result body when the probe passes."""
        mock_tasks_api_dep.post.return_value = {
            "success": True,
            "error": None,
            "task_history_id": _TASK_HISTORY_ID,
        }
        response = test_client.post(self._url(mysql_service))
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "success": True,
            "error": None,
            "task_history_id": _TASK_HISTORY_ID,
        }
        mock_tasks_api_dep.post.assert_awaited_once_with(
            "/connectivity-check/",
            json={
                "target": mysql_service.node.name,
                "host": mysql_service.node.address,
                "port": mysql_service.port,
                "service_type": ServiceTypeEnum.MYSQL.value,
            },
        )

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_failed_probe_returns_200_with_error_body(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Return HTTP 200 with ``success=false`` when the check fails but the call succeeds."""
        mock_tasks_api_dep.post.return_value = {
            "success": False,
            "error": "Connection refused",
            "task_history_id": _TASK_HISTORY_ID,
        }
        response = test_client.post(self._url(mysql_service))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["success"] is False
        assert body["error"] == "Connection refused"

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_failed_probe_without_error_returns_null_error(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Keep ``error`` null on an errorless failure so the client owns the fallback text."""
        mock_tasks_api_dep.post.return_value = {
            "success": False,
            "error": None,
            "task_history_id": _TASK_HISTORY_ID,
        }
        response = test_client.post(self._url(mysql_service))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["success"] is False
        assert body["error"] is None

    @pytest.mark.usefixtures("mock_tasks_api_dep")
    def test_unsupported_service_type_returns_400(
        self, test_client, created_node, mock_tasks_api_dep
    ):
        """Reject a non-connectable service type server-side with HTTP 400."""
        service = CreatedServiceFactory.build(
            type=ServiceTypeEnum.PROXYSQL, port=_MYSQL_PORT
        )
        service.node = created_node
        sep_app.dependency_overrides[get_created_service] = lambda: service
        try:
            response = test_client.post(self._url(service))
        finally:
            sep_app.dependency_overrides.pop(get_created_service, None)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert ServiceTypeEnum.PROXYSQL.name in response.json()["detail"]
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_missing_port_returns_400(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Reject a service with no port, which cannot be probed, with HTTP 400."""
        mysql_service.port = None
        response = test_client.post(self._url(mysql_service))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_unregistered_node_address_returns_400_naming_the_address(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Return HTTP 400 naming the node address when no executor is registered for it."""
        mock_tasks_api_dep.get.return_value = {"some-other-nomad": "10.0.0.99"}
        response = test_client.post(self._url(mysql_service))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert mysql_service.node.address in response.json()["detail"]
        mock_tasks_api_dep.post.assert_not_awaited()

    @pytest.mark.usefixtures("mock_tasks_api_dep")
    def test_unknown_service_propagates_404(self, test_client, mock_inventory_api_dep):
        """Propagate the inventory 404 from ``CreatedServiceDep`` for an unknown service id."""
        mock_inventory_api_dep.get.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service not found"
        )
        response = test_client.post(
            "/api/apps/inventory/services/999999/check-connectivity/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_unreachable_tasks_api_returns_502_without_leaking_internals(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Surface a transport failure as HTTP 502 with no internal error text."""
        mock_tasks_api_dep.post.side_effect = ConnectionError("boom at socket layer")
        response = test_client.post(self._url(mysql_service))
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "boom at socket layer" not in response.text

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_malformed_upstream_payload_returns_502(
        self, test_client, mysql_service, mock_tasks_api_dep
    ):
        """Return HTTP 502 for an unparseable upstream body, not a 500 validation escape."""
        mock_tasks_api_dep.post.return_value = {"unexpected": "shape"}
        response = test_client.post(self._url(mysql_service))
        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    @pytest.mark.usefixtures("_mock_mysql_service_dep")
    def test_requires_authentication(self, unauthenticated_client, mysql_service):
        """Return 401 when the request carries no API auth."""
        response = unauthenticated_client.post(self._url(mysql_service))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_openapi_response_references_connectivity_model(self, test_client):
        """Reference the upstream connectivity model from the 200 response schema."""
        spec = test_client.get("/openapi.json").json()
        post_op = spec["paths"][
            "/api/apps/inventory/services/{service_id}/check-connectivity/"
        ]["post"]
        schema = post_op["responses"]["200"]["content"]["application/json"]["schema"]
        assert "ConnectivityCheckResponse" in schema["$ref"]
