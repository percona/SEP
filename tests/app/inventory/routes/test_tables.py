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

"""Define tests for inventory table routes."""

from starlette import status
from starlette.testclient import TestClient

from app.core.pagination import DEFAULT_PAGINATION_LIMIT
from app.inventory.models import Schema, Service, Table
from tests.app.factories import SchemaWriteFactory, TableWriteFactory

EXPECTED_TABLE_COUNT = 2
OFFSET_BEYOND_TOTAL = 999


class TestListTables:
    """Test the GET /tables/ endpoint."""

    def test_list_tables_empty(self, test_client: TestClient) -> None:
        """Return an empty paginated response when no tables exist."""
        response = test_client.get("/tables/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["offset"] == 0
        assert data["limit"] == DEFAULT_PAGINATION_LIMIT

    def test_list_tables_multiple(
        self, test_client: TestClient, table: Table, second_table: Table
    ) -> None:
        """Return a list of all tables."""
        response = test_client.get("/tables/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == EXPECTED_TABLE_COUNT
        assert data["total"] == EXPECTED_TABLE_COUNT
        returned_ids = {t["id"] for t in data["items"]}
        assert returned_ids == {table.id, second_table.id}

    def test_list_tables_custom_offset(
        self, test_client: TestClient, table: Table
    ) -> None:
        """Return empty items when offset is beyond total."""
        response = test_client.get("/tables/", params={"offset": OFFSET_BEYOND_TOTAL})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 1
        assert data["offset"] == OFFSET_BEYOND_TOTAL

    def test_list_tables_custom_limit(
        self, test_client: TestClient, table: Table, second_table: Table
    ) -> None:
        """Return limited items while total remains unchanged."""
        response = test_client.get("/tables/", params={"limit": 1})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == EXPECTED_TABLE_COUNT
        assert data["limit"] == 1


class TestRetrieveTable:
    """Test the GET /tables/{table_id} endpoint."""

    def test_retrieve_table(
        self, test_client: TestClient, table: Table, schema: Schema
    ) -> None:
        """Return the table with its parent schema in the database field."""
        response = test_client.get(f"/tables/{table.id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == table.id
        assert data["name"] == table.name
        assert "database" in data
        assert data["database"]["id"] == schema.id

    def test_retrieve_table_not_found(self, test_client: TestClient) -> None:
        """Return 404 when the table does not exist."""
        response = test_client.get("/tables/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestUpdateTable:
    """Test the PUT /tables/{table_id} endpoint."""

    def test_update_table(
        self, test_client: TestClient, table: Table, schema: Schema
    ) -> None:
        """Update the table name and return the updated table."""
        payload = TableWriteFactory.build(
            name="updated_table_name",
            create=table.create,
            keys=table.keys,
            schema_id=schema.id,
        ).model_dump(mode="json")
        response = test_client.put(f"/tables/{table.id}", json=payload)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "updated_table_name"

    def test_update_table_not_found(
        self, test_client: TestClient, schema: Schema
    ) -> None:
        """Return 404 when updating a nonexistent table."""
        payload = TableWriteFactory.build(schema_id=schema.id).model_dump(mode="json")
        response = test_client.put("/tables/99999", json=payload)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_table_invalid_schema_id(
        self, test_client: TestClient, table: Table
    ) -> None:
        """Return 400 when schema_id references a nonexistent schema."""
        payload = TableWriteFactory.build(schema_id=99999).model_dump(mode="json")
        response = test_client.put(f"/tables/{table.id}", json=payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Invalid schema_id: 99999"

    def test_update_table_omitting_schema_id_preserves_parent(
        self, test_client: TestClient, service: Service, schema: Schema, table: Table
    ) -> None:
        """Apply a partial update that omits schema_id, leaving the parent unchanged.

        A second schema must exist so the previously-dropped ``None`` FK filter
        would match more than one parent (HTTP 500) rather than silently pass.
        """
        second = test_client.post(
            f"/services/{service.id}/schemas/",
            json=SchemaWriteFactory.build(name=f"second_schema_{schema.id}").model_dump(
                mode="json"
            ),
        )
        assert second.status_code == status.HTTP_201_CREATED
        response = test_client.put(
            f"/tables/{table.id}",
            json={
                "name": "renamed_table",
                "create": table.create,
                "keys": table.keys,
            },
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "renamed_table"
        assert data["schema_id"] == schema.id

    def test_update_table_omitting_schema_id_preserves_association(
        self, test_client: TestClient, table: Table, schema: Schema, service: Service
    ) -> None:
        """Partial update without schema_id succeeds and leaves the FK unchanged."""
        test_client.post(
            "/schemas/",
            json=SchemaWriteFactory.build(service_id=service.id).model_dump(
                mode="json"
            ),
        )
        payload = {
            "name": "renamed_table",
            "create": table.create,
            "keys": table.keys,
        }
        response = test_client.put(f"/tables/{table.id}", json=payload)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "renamed_table"
        assert data["schema_id"] == schema.id

    def test_update_table_explicit_null_schema_id(
        self, test_client: TestClient, table: Table
    ) -> None:
        """Return 400 when schema_id is explicitly null on a non-nullable relationship."""
        payload = {
            "name": table.name,
            "create": table.create,
            "keys": table.keys,
            "schema_id": None,
        }
        response = test_client.put(f"/tables/{table.id}", json=payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Invalid schema_id: None"


class TestDeleteTable:
    """Test the DELETE /tables/{table_id} endpoint."""

    def test_delete_table(self, test_client: TestClient, table: Table) -> None:
        """Delete a table and confirm it is gone."""
        response = test_client.delete(f"/tables/{table.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        response = test_client.get(f"/tables/{table.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_table_not_found(self, test_client: TestClient) -> None:
        """Return 404 when deleting a nonexistent table."""
        response = test_client.delete("/tables/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND
