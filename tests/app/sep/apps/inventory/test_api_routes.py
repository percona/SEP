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

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from pydantic import SecretStr

from app.core.config import settings
from app.core.exceptions import HTTPServiceUnavailableException
from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.inventory import api_routes as inventory_api_routes
from app.sep.apps.inventory.api_routes import _topology_event_stream
from app.sep.apps.inventory.deps import (
    get_syncers,
    INVENTORY_PLUGIN_ENTITY_NAMES,
)
from app.sep.apps.inventory.models import MAX_TOPOLOGY_SHARDS
from app.sep.apps.inventory.topology import TOPOLOGY_JOB_PREFIX
from app.sep.crud import SyncItemManager
from app.sep.deps import BEARER_REQUIRED_DETAIL
from app.sep.main import sep_app
from app.sep.models import SyncInventoryEntityTypeEnum
from tests.app.sep.apps.inventory.conftest import no_syncers, PMM_STUB_NAME

_EXPECTED_SCHEMA_ENTITY_COUNT = len(INVENTORY_PLUGIN_ENTITY_NAMES)
_CREATE_SERVICE_TEST_NODE_ID = 7


class TestInventoryResponseModelsInOpenAPI:
    """Ensure new endpoints expose typed Pydantic models in the OpenAPI schema."""

    def test_plugin_tasks_response_schema_is_defined(self, test_client):
        """Ensure PluginTaskResponse appears as a named schema in the OpenAPI spec."""
        response = test_client.get("/openapi.json")
        assert response.status_code == status.HTTP_200_OK
        schemas = response.json().get("components", {}).get("schemas", {})
        assert "PluginTaskResponse" in schemas

    def test_available_syncers_response_schema_is_defined(self, test_client):
        """Ensure AvailableSyncer appears as a named schema in the OpenAPI spec."""
        response = test_client.get("/openapi.json")
        assert response.status_code == status.HTTP_200_OK
        schemas = response.json().get("components", {}).get("schemas", {})
        assert "AvailableSyncer" in schemas

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
        assert body["capabilities"]["topology"] is False

    def test_schema_reflects_topology_feature_flag(self, test_client, monkeypatch):
        """Ensure the schema exposes the runtime topology capability."""
        monkeypatch.setattr(
            inventory_api_routes.sep_settings, "INVENTORY_TOPOLOGY_ENABLED", True
        )

        response = test_client.get("/api/plugins/inventory/schema")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["capabilities"]["topology"] is True


class TestInventoryGateway:
    """Tests for inventory CRUD proxy routes under ``/api/apps/inventory/``."""

    def test_list_nodes_unwraps_items(self, test_client, mock_inventory_api_dep):
        """Ensure GET ``/api/apps/inventory/nodes/`` unwraps paginated ``items`` to a JSON array."""
        mock_inventory_api_dep.get.return_value = {
            "items": [{"id": 1, "name": "n"}],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get("/api/apps/inventory/nodes/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [{"id": 1, "name": "n"}]
        mock_inventory_api_dep.get.assert_awaited_once_with("/nodes/", params={})

    def test_list_forwards_query_params_to_inventory(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure list route forwards query params to the inventory API."""
        mock_inventory_api_dep.get.return_value = {"items": [], "total": 0}
        response = test_client.get(
            "/api/apps/inventory/nodes/",
            params={"limit": 10},
        )
        assert response.status_code == status.HTTP_200_OK
        mock_inventory_api_dep.get.assert_awaited_once_with(
            "/nodes/",
            params={"limit": "10"},
        )

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
            response_schema = openapi["paths"]["/api/plugins/inventory/sync/status/"][
                "get"
            ]["responses"]["200"]["content"]["application/json"]["schema"]
            assert "$ref" in response_schema, (
                "Expected a $ref to InventorySyncStatusResponse; got inline schema. "
                "Change the return type annotation back to InventorySyncStatusResponse."
            )
        finally:
            sep_app.openapi_schema = prior_schema


def _mysql_service(
    service_id: int, address: str, port: int = DEFAULT_MYSQL_PORT
) -> dict:
    return {
        "id": service_id,
        "name": f"svc-{service_id}",
        "type": ServiceTypeEnum.MYSQL.value,
        "port": port,
        "node": {"id": service_id, "name": address, "address": address},
    }


def _topology_history(history_id: int, status_value: str, user_id: str) -> dict:
    return {
        "id": history_id,
        "status": status_value,
        "executed_by": user_id,
        "execution_request": {
            "task": "run-python",
            "meta": {"_job_id_prefix": TOPOLOGY_JOB_PREFIX},
        },
    }


class TestTopologyCollect:
    """Tests for ``POST /api/plugins/inventory/topology/collect``."""

    @pytest.fixture(autouse=True)
    def _enable_topology(self, monkeypatch):
        monkeypatch.setattr(
            inventory_api_routes.sep_settings, "INVENTORY_TOPOLOGY_ENABLED", True
        )

    def test_returns_404_when_topology_disabled(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep, monkeypatch
    ):
        """Ensure topology collect is hidden while the feature flag is off."""
        monkeypatch.setattr(
            inventory_api_routes.sep_settings, "INVENTORY_TOPOLOGY_ENABLED", False
        )

        response = test_client.post("/api/plugins/inventory/topology/collect", json={})

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_inventory_api_dep.get.assert_not_called()
        mock_task_api_dep.post.assert_not_called()

    def test_dispatches_one_task_per_shard(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """Ensure topology collect splits hosts across shards and dispatches run-python tasks."""
        mock_inventory_api_dep.get.return_value = {
            "items": [
                _mysql_service(1, "10.0.0.1"),
                _mysql_service(2, "10.0.0.2"),
                _mysql_service(3, "10.0.0.3"),
            ]
        }
        mock_task_api_dep.get.return_value = {
            "executor-a": "1.1.1.1",
            "executor-b": "2.2.2.2",
        }
        mock_task_api_dep.post.side_effect = [{"id": 101}, {"id": 102}]

        response = test_client.post(
            "/api/plugins/inventory/topology/collect", json={"shards": 2}
        )

        expected_shard_count = 2
        expected_host_count = 3
        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        assert body["task_history_ids"] == [101, 102]
        assert body["shard_count"] == expected_shard_count
        assert body["host_count"] == expected_host_count
        assert mock_task_api_dep.post.await_count == expected_shard_count

    def test_returns_404_when_no_mysql_services_exist(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """Ensure topology collect 404s when the inventory has no MySQL services."""
        mock_inventory_api_dep.get.return_value = {"items": []}
        mock_task_api_dep.get.return_value = {"executor-a": "1.1.1.1"}
        response = test_client.post("/api/plugins/inventory/topology/collect", json={})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_rejects_unknown_executor_host(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """Ensure an explicit, unknown executor_host yields 400."""
        mock_inventory_api_dep.get.return_value = {
            "items": [_mysql_service(1, "10.0.0.1")]
        }
        mock_task_api_dep.get.return_value = {"executor-a": "1.1.1.1"}
        response = test_client.post(
            "/api/plugins/inventory/topology/collect",
            json={"executor_host": "missing"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_executor_host_with_multiple_shards(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """Ensure explicit executor mode cannot silently ignore shards."""
        response = test_client.post(
            "/api/plugins/inventory/topology/collect",
            json={"executor_host": "executor-a", "shards": 4},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "executor_host requires shards=1" in response.text
        mock_inventory_api_dep.get.assert_not_called()
        mock_task_api_dep.post.assert_not_called()

    @pytest.mark.parametrize("hosts_payload", [None, []])
    def test_rejects_invalid_executor_hosts_payload(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep, hosts_payload
    ):
        """Ensure malformed Tasks API hosts payloads produce a friendly 502."""
        mock_inventory_api_dep.get.return_value = {
            "items": [_mysql_service(1, "10.0.0.1")]
        }
        mock_task_api_dep.get.return_value = hosts_payload

        response = test_client.post("/api/plugins/inventory/topology/collect", json={})

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json()["detail"] == (
            "Tasks API returned an invalid executor hosts payload."
        )


def _stdout_stream(stdout: str):
    """Return an async-iterator factory producing the framed log stream."""

    async def _stream(_path, params=None):
        yield json.dumps({"type": "stdout", "msg": stdout}).encode("utf-8")

    return _stream


def _host_done_stdout(host: str) -> str:
    return json.dumps(
        {
            "event": "host_done",
            "host": host,
            "data": {
                "address": host.rsplit(":", 1)[0],
                "port": DEFAULT_MYSQL_PORT,
                "server": {"server_hash": f"hash-{host}", "server_id": 1},
                "replication": {},
                "cluster": {},
                "gtid_mode": "",
            },
        }
    )


class TestTopologyResult:
    """Tests for ``GET /api/plugins/inventory/topology/result``."""

    @pytest.fixture(autouse=True)
    def _enable_topology(self, monkeypatch):
        monkeypatch.setattr(
            inventory_api_routes.sep_settings, "INVENTORY_TOPOLOGY_ENABLED", True
        )

    def test_running_status_when_any_task_pending(
        self, test_client, mock_task_api_dep, regular_user
    ):
        """Ensure result endpoint reports ``running`` while any task is unfinished."""
        user_id = str(regular_user.id)
        mock_task_api_dep.get.side_effect = [
            _topology_history(1, "success", user_id),
            _topology_history(2, "running", user_id),
        ]
        response = test_client.get(
            "/api/plugins/inventory/topology/result", params={"ids": "1,2"}
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "running"
        assert body["pending_task_ids"] == [2]
        assert body["graph"] is None

    @pytest.mark.parametrize("terminal_status", ["failed", "lost", "stopped", "stale"])
    def test_terminal_failure_with_no_stdout_returns_failed(
        self, test_client, mock_task_api_dep, regular_user, terminal_status: str
    ):
        """Ensure unsuccessful terminal tasks with no graph data do not report ``ok``."""
        mock_task_api_dep.get.return_value = _topology_history(
            9, terminal_status, str(regular_user.id)
        )
        mock_task_api_dep.stream = _stdout_stream("")

        response = test_client.get(
            "/api/plugins/inventory/topology/result", params={"ids": "9"}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "failed"
        assert body["pending_task_ids"] == []
        assert body["failed_task_ids"] == [9]
        assert body["graph"]["nodes"] == []

    def test_partial_shard_failure_returns_failed_task_ids(
        self, test_client, mock_task_api_dep, regular_user
    ):
        """Ensure whole-shard failures remain visible when other shards return a graph."""
        user_id = str(regular_user.id)
        mock_task_api_dep.get.side_effect = [
            _topology_history(1, "success", user_id),
            _topology_history(2, "failed", user_id),
        ]

        async def _stream(path, params=None):
            if "/history/1/" in path:
                yield json.dumps(
                    {"type": "stdout", "msg": _host_done_stdout("h1:3306")}
                ).encode("utf-8")

        mock_task_api_dep.stream = _stream

        response = test_client.get(
            "/api/plugins/inventory/topology/result", params={"ids": "1,2"}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "ok"
        assert body["failed_task_ids"] == [2]
        assert body["graph"]["nodes"]

    @pytest.mark.parametrize("route", ["result", "stream"])
    def test_rejects_too_many_ids(self, test_client, mock_task_api_dep, route: str):
        """Ensure result and stream endpoints cap task fan-out."""
        ids = ",".join(str(i) for i in range(1, MAX_TOPOLOGY_SHARDS + 2))
        response = test_client.get(
            f"/api/plugins/inventory/topology/{route}", params={"ids": ids}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "task history ids are allowed" in response.text
        mock_task_api_dep.get.assert_not_called()

    @pytest.mark.parametrize("route", ["result", "stream"])
    def test_rejects_other_users_task_history(
        self, test_client, mock_task_api_dep, route: str
    ):
        """Ensure topology endpoints do not expose another user's task output."""
        mock_task_api_dep.get.return_value = _topology_history(
            77, "success", "other-user-id"
        )
        response = test_client.get(
            f"/api/plugins/inventory/topology/{route}", params={"ids": "77"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Task history is not accessible" in response.text
        mock_task_api_dep.stream.assert_not_called()

    def test_rejects_non_topology_task_history(
        self, test_client, mock_task_api_dep, regular_user
    ):
        """Ensure guessed non-topology task ids cannot be reused by topology result."""
        history = _topology_history(77, "success", str(regular_user.id))
        history["execution_request"]["meta"]["_job_id_prefix"] = "backup"
        mock_task_api_dep.get.return_value = history
        response = test_client.get(
            "/api/plugins/inventory/topology/result", params={"ids": "77"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Task history is not accessible" in response.text
        mock_task_api_dep.stream.assert_not_called()

    def test_invalid_ids_yields_400(self, test_client, mock_task_api_dep):
        """Ensure non-integer ids in the query string return HTTP 400."""
        response = test_client.get(
            "/api/plugins/inventory/topology/result", params={"ids": "abc"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_ids_yields_422(self, test_client, mock_task_api_dep):
        """Ensure the ids query parameter is required."""
        response = test_client.get("/api/plugins/inventory/topology/result")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestTopologyStream:
    """Tests for ``GET /api/plugins/inventory/topology/stream`` internals."""

    @pytest.mark.asyncio
    async def test_polling_error_emits_task_error_before_done(self):
        """Ensure task-history polling failures surface as SSE task_error events."""

        class BrokenTasksAPI:
            async def get(self, _path):
                raise HTTPServiceUnavailableException("Tasks API unavailable")

        events = []
        async for event in _topology_event_stream(BrokenTasksAPI(), [77]):
            events.append(event)
            if event.startswith("event: complete"):
                break

        assert any("event: task_error" in event for event in events)
        assert any('"status_code":503' in event for event in events)
        assert any('"detail":"Tasks API unavailable"' in event for event in events)
        assert any("event: task_done" in event for event in events)

    @pytest.mark.asyncio
    async def test_worker_crash_is_logged(self, monkeypatch):
        """Ensure unexpected worker exceptions are not silently swallowed."""

        class BrokenStreamTasksAPI:
            async def get(self, _path):
                return {"id": 77, "status": "running"}

            async def stream(self, _path, params=None):
                raise RuntimeError("stream broke")
                yield b""

        logged_messages: list[str] = []

        def _capture_exception(message: str) -> None:
            logged_messages.append(message)

        monkeypatch.setattr(
            inventory_api_routes.logger, "exception", _capture_exception
        )

        events = [
            event
            async for event in _topology_event_stream(BrokenStreamTasksAPI(), [77])
        ]

        assert any("event: task_done" in event for event in events)
        assert any("event: complete" in event for event in events)
        assert logged_messages == ["Topology stream worker failed."]
