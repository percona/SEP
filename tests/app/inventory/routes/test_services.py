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

"""Define tests for inventory service routes."""

from starlette import status
from starlette.testclient import TestClient

from app.inventory.models import Node, Schema, Service
from tests.app.factories import SchemaWriteFactory, ServiceWriteFactory


class TestListServices:
    """Test GET /services/ endpoint."""

    def test_list_services_empty(self, test_client: TestClient) -> None:
        """Return an empty list when no services exist."""
        response = test_client.get("/services/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_services_multiple(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return all services with schemas and node loaded."""
        response = test_client.get("/services/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == service.id
        assert "schemas" in data[0]
        assert "node" in data[0]

    def test_list_services_filter_by_service_type(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return only services matching the requested service type."""
        response = test_client.get(
            "/services/",
            params={"service_type": service.type},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) >= 1
        assert all(s["type"] == service.type for s in data)


class TestRetrieveService:
    """Test GET /services/{service_id} endpoint."""

    def test_retrieve_service(self, test_client: TestClient, service: Service) -> None:
        """Return the service with schemas and node."""
        response = test_client.get(f"/services/{service.id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == service.id
        assert "schemas" in data
        assert "node" in data

    def test_retrieve_service_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent service ID."""
        response = test_client.get("/services/9999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestUpdateService:
    """Test PUT /services/{service_id} endpoint."""

    def test_update_service(
        self, test_client: TestClient, service: Service, node: Node
    ) -> None:
        """Update a service name and return the updated service."""
        payload = ServiceWriteFactory.build(node_id=node.id)
        payload.name = "updated-service-name"
        response = test_client.put(
            f"/services/{service.id}",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "updated-service-name"

    def test_update_service_not_found(
        self, test_client: TestClient, node: Node
    ) -> None:
        """Return 404 when updating a nonexistent service."""
        payload = ServiceWriteFactory.build(node_id=node.id)
        response = test_client.put(
            "/services/9999",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_service_invalid_node_id(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return 400 when updating with a nonexistent node_id."""
        payload = ServiceWriteFactory.build(node_id=9999)
        response = test_client.put(
            f"/services/{service.id}",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestDeleteService:
    """Test DELETE /services/{service_id} endpoint."""

    def test_delete_service(self, test_client: TestClient, service: Service) -> None:
        """Delete a service and confirm it is gone."""
        response = test_client.delete(f"/services/{service.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        response = test_client.get(f"/services/{service.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_service_not_found(self, test_client: TestClient) -> None:
        """Return 404 when deleting a nonexistent service."""
        response = test_client.delete("/services/9999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestListSchemasByService:
    """Test GET /services/{service_id}/schemas/ endpoint."""

    def test_list_schemas_by_service_empty(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return an empty list when the service has no schemas."""
        response = test_client.get(f"/services/{service.id}/schemas/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_schemas_by_service(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return compact schemas without tables for the given service."""
        response = test_client.get(f"/services/{service.id}/schemas/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == schema.id
        assert "tables" not in data[0]

    def test_list_schemas_by_service_search(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return only schemas whose name matches the search query."""
        response = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"search": schema.name[:3]},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == schema.id

    def test_list_schemas_by_service_search_no_match(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return empty list when search does not match any schema."""
        response = test_client.get(
            f"/services/{service.id}/schemas/",
            params={"search": "nonexistent_schema_xyz"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_schemas_by_service_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent service ID."""
        response = test_client.get("/services/9999/schemas/")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestCreateSchemaForService:
    """Test POST /services/{service_id}/schemas/ endpoint."""

    def test_create_schema_for_service(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Create a schema for a service and return 201."""
        payload = SchemaWriteFactory.build()
        response = test_client.post(
            f"/services/{service.id}/schemas/",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["name"] == payload.name

    def test_create_schema_for_service_duplicate_name(
        self, test_client: TestClient, service: Service, schema: Schema
    ) -> None:
        """Return 409 when creating a schema with a duplicate name."""
        payload = SchemaWriteFactory.build()
        payload.name = schema.name
        response = test_client.post(
            f"/services/{service.id}/schemas/",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_create_schema_for_service_not_found(self, test_client: TestClient) -> None:
        """Return 404 when creating a schema for a nonexistent service."""
        payload = SchemaWriteFactory.build()
        response = test_client.post(
            "/services/9999/schemas/",
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
