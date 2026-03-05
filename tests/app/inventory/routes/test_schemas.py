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

"""Define tests for inventory schema routes."""

from starlette import status
from starlette.testclient import TestClient

from app.inventory.models import Schema, Service, Table
from tests.app.factories import SchemaWriteFactory, TableWriteFactory

SCHEMA_COUNT_WITH_SECOND = 2


class TestListSchemas:
    """Test GET /schemas/ endpoint."""

    def test_list_schemas_empty(self, test_client: TestClient) -> None:
        """Return an empty list when no schemas exist."""
        response = test_client.get("/schemas/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_schemas_multiple(
        self, test_client: TestClient, schema: Schema, service: Service
    ) -> None:
        """Return a list of schemas with tables loaded."""
        second = SchemaWriteFactory.build()
        test_client.post(
            f"/services/{service.id}/schemas/",
            json=second.model_dump(),
        )

        response = test_client.get("/schemas/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert len(data) == SCHEMA_COUNT_WITH_SECOND
        assert all("tables" in s for s in data)


class TestRetrieveSchema:
    """Test GET /schemas/{schema_id} endpoint."""

    def test_retrieve_schema(
        self, test_client: TestClient, schema: Schema, table: Table
    ) -> None:
        """Return schema detail with tables and service."""
        response = test_client.get(f"/schemas/{schema.id}")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["id"] == schema.id
        assert isinstance(data["tables"], list)
        assert len(data["tables"]) == 1
        assert "service" in data
        assert data["service"]["id"] == schema.service_id

    def test_retrieve_schema_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent schema."""
        response = test_client.get("/schemas/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestUpdateSchema:
    """Test PUT /schemas/{schema_id} endpoint."""

    def test_update_schema(self, test_client: TestClient, schema: Schema) -> None:
        """Update a schema name successfully."""
        payload = {"name": "updated_schema", "service_id": schema.service_id}
        response = test_client.put(f"/schemas/{schema.id}", json=payload)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "updated_schema"

    def test_update_schema_not_found(
        self, test_client: TestClient, service: Service
    ) -> None:
        """Return 404 for updating a nonexistent schema."""
        payload = {"name": "no_matter", "service_id": service.id}
        response = test_client.put("/schemas/99999", json=payload)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_schema_invalid_service_id(
        self, test_client: TestClient, schema: Schema
    ) -> None:
        """Return 400 when service_id references a nonexistent service."""
        payload = {"name": schema.name, "service_id": 99999}
        response = test_client.put(f"/schemas/{schema.id}", json=payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestDeleteSchema:
    """Test DELETE /schemas/{schema_id} endpoint."""

    def test_delete_schema(self, test_client: TestClient, schema: Schema) -> None:
        """Delete a schema and confirm it is gone."""
        response = test_client.delete(f"/schemas/{schema.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        response = test_client.get(f"/schemas/{schema.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_schema_not_found(self, test_client: TestClient) -> None:
        """Return 404 for deleting a nonexistent schema."""
        response = test_client.delete("/schemas/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestListTablesBySchema:
    """Test GET /schemas/{schema_id}/tables/ endpoint."""

    def test_list_tables_by_schema_empty(
        self, test_client: TestClient, schema: Schema
    ) -> None:
        """Return an empty list when schema has no tables."""
        response = test_client.get(f"/schemas/{schema.id}/tables/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_tables_by_schema(
        self, test_client: TestClient, schema: Schema, table: Table
    ) -> None:
        """Return tables belonging to the schema."""
        response = test_client.get(f"/schemas/{schema.id}/tables/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == table.id

    def test_list_tables_by_schema_not_found(self, test_client: TestClient) -> None:
        """Return 404 for a nonexistent schema."""
        response = test_client.get("/schemas/99999/tables/")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestCreateTableForSchema:
    """Test POST /schemas/{schema_id}/tables/ endpoint."""

    def test_create_table_for_schema(
        self, test_client: TestClient, schema: Schema
    ) -> None:
        """Create a table under a schema successfully."""
        payload = TableWriteFactory.build().model_dump()
        response = test_client.post(f"/schemas/{schema.id}/tables/", json=payload)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["name"] == payload["name"]
        assert response.json()["schema_id"] == schema.id

    def test_create_table_for_schema_duplicate_name(
        self, test_client: TestClient, schema: Schema, table: Table
    ) -> None:
        """Return 409 when creating a table with a duplicate name in the same schema."""
        payload = {"name": table.name, "create": "CREATE TABLE t(id INT)", "keys": {}}
        response = test_client.post(f"/schemas/{schema.id}/tables/", json=payload)
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_create_table_for_schema_not_found(self, test_client: TestClient) -> None:
        """Return 404 when creating a table under a nonexistent schema."""
        payload = TableWriteFactory.build().model_dump()
        response = test_client.post("/schemas/99999/tables/", json=payload)
        assert response.status_code == status.HTTP_404_NOT_FOUND
