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

"""Define tests for the inventory plugin JSON API routes under ``/api/plugins/inventory/``.

Path mapping, entity validation, list unwrapping, and query forwarding are
implemented in ``app.sep.plugins.inventory.deps``; see
``tests/app/sep/plugins/inventory/test_deps.py`` for direct unit coverage.
"""

import pytest
from fastapi import status

from app.sep.plugins.inventory.deps import INVENTORY_PLUGIN_ENTITY_NAMES

_EXPECTED_SCHEMA_ENTITY_COUNT = len(INVENTORY_PLUGIN_ENTITY_NAMES)
_CREATE_SERVICE_TEST_NODE_ID = 7


class TestInventorySchemaEndpoint:
    """Tests for GET /api/plugins/inventory/schema."""

    def test_schema_returns_200(self, test_client):
        """Ensure the schema endpoint returns HTTP 200 with the expected plugin body."""
        response = test_client.get("/api/plugins/inventory/schema")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "inventory"
        assert len(body["entities"]) == _EXPECTED_SCHEMA_ENTITY_COUNT


class TestInventoryGateway:
    """Tests for inventory CRUD proxy routes under ``/api/plugins/inventory/``."""

    def test_list_nodes_unwraps_items(self, test_client, mock_inventory_api_dep):
        """Ensure GET ``/api/plugins/inventory/nodes/`` unwraps paginated ``items`` to a JSON array."""
        mock_inventory_api_dep.get.return_value = {
            "items": [{"id": 1, "name": "n"}],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get("/api/plugins/inventory/nodes/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [{"id": 1, "name": "n"}]
        mock_inventory_api_dep.get.assert_awaited_once_with("/", params={})

    def test_list_forwards_query_params_to_inventory(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure list route forwards query params to the inventory API."""
        mock_inventory_api_dep.get.return_value = {"items": [], "total": 0}
        response = test_client.get(
            "/api/plugins/inventory/nodes/",
            params={"limit": 10},
        )
        assert response.status_code == status.HTTP_200_OK
        mock_inventory_api_dep.get.assert_awaited_once_with(
            "/",
            params={"limit": "10"},
        )

    def test_unknown_entity_404(self, test_client, mock_inventory_api_dep):
        """Ensure GET on an unknown entity segment returns HTTP 404."""
        response = test_client.get("/api/plugins/inventory/unknown/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_service_forwards_to_node_services(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure POST ``/api/plugins/inventory/services/`` maps to ``/{node_id}/services/`` on inventory."""
        mock_inventory_api_dep.post.return_value = {"id": 2, "name": "svc"}
        response = test_client.post(
            "/api/plugins/inventory/services/",
            json={
                "node_id": _CREATE_SERVICE_TEST_NODE_ID,
                "name": "db",
                "type": "mysql",
            },
        )
        assert response.status_code == status.HTTP_200_OK
        mock_inventory_api_dep.post.assert_awaited_once()
        call_args = mock_inventory_api_dep.post.await_args
        assert call_args[0][0] == f"/{_CREATE_SERVICE_TEST_NODE_ID}/services/"
        assert call_args[1]["json"]["node_id"] == _CREATE_SERVICE_TEST_NODE_ID

    def test_create_service_invalid_node_id_returns_422(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure non-numeric ``node_id`` returns HTTP 422 and does not call inventory."""
        response = test_client.post(
            "/api/plugins/inventory/services/",
            json={
                "node_id": "abc",
                "name": "db",
                "type": "mysql",
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_inventory_api_dep.post.assert_not_called()

    def test_create_schema_requires_service_id(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure POST ``/api/plugins/inventory/schemas/`` without ``service_id`` returns HTTP 422."""
        response = test_client.post(
            "/api/plugins/inventory/schemas/",
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
            "/api/plugins/inventory/nodes/",
            content=raw_content,
            headers={"Content-Type": content_type},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert response.json()["detail"] == "JSON object body required"
        mock_inventory_api_dep.post.assert_not_called()

    def test_delete_returns_204(self, test_client, mock_inventory_api_dep):
        """Ensure DELETE ``/api/plugins/inventory/nodes/{id}`` returns HTTP 204 with an empty body."""
        mock_inventory_api_dep.delete.return_value = None
        response = test_client.delete("/api/plugins/inventory/nodes/3")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""
        mock_inventory_api_dep.delete.assert_awaited_once_with("/3")

    @pytest.mark.parametrize(
        ("entity", "item_id", "inventory_path"),
        [
            ("nodes", 3, "/3"),
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
        response = test_client.get(f"/api/plugins/inventory/{entity}/{item_id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload
        mock_inventory_api_dep.get.assert_awaited_once_with(inventory_path)

    @pytest.mark.parametrize(
        ("entity", "item_id", "inventory_path"),
        [
            ("nodes", 3, "/3"),
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
            f"/api/plugins/inventory/{entity}/{item_id}",
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
        response = test_client.get("/api/plugins/inventory/unknown/1")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_inventory_api_dep.get.assert_not_called()
