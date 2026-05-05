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

from urllib.parse import urlsplit

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

    def test_list_no_trailing_slash_redirect_preserves_query_string(
        self, test_client, mock_inventory_api_dep
    ):
        """Ensure ``GET …/nodes`` redirects to ``…/nodes/?…`` with query params intact."""
        mock_inventory_api_dep.get.return_value = {"items": [], "total": 0}
        response = test_client.get(
            "/api/plugins/inventory/nodes",
            params={"limit": 10},
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_307_TEMPORARY_REDIRECT
        location = response.headers["location"]
        parts = urlsplit(location)
        assert parts.path.endswith("/nodes/")
        assert parts.query == "limit=10"

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

    def test_delete_returns_204(self, test_client, mock_inventory_api_dep):
        """Ensure DELETE ``/api/plugins/inventory/nodes/{id}`` returns HTTP 204 with an empty body."""
        mock_inventory_api_dep.delete.return_value = {}
        response = test_client.delete("/api/plugins/inventory/nodes/3")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""
        mock_inventory_api_dep.delete.assert_awaited_once_with("/3")
