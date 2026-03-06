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

from app.inventory.models import Schema, Table

EXPECTED_TABLE_COUNT = 2


class TestListTables:
    """Test the GET /tables/ endpoint."""

    def test_list_tables_empty(self, test_client: TestClient) -> None:
        """Return an empty list when no tables exist."""
        response = test_client.get("/tables/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_tables_multiple(
        self, test_client: TestClient, table: Table, second_table: Table
    ) -> None:
        """Return a list of all tables."""
        response = test_client.get("/tables/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == EXPECTED_TABLE_COUNT
        returned_ids = {t["id"] for t in data}
        assert returned_ids == {table.id, second_table.id}


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
        payload = {
            "name": "updated_table_name",
            "create": table.create,
            "keys": table.keys,
            "schema_id": schema.id,
        }
        response = test_client.put(f"/tables/{table.id}", json=payload)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "updated_table_name"

    def test_update_table_not_found(
        self, test_client: TestClient, schema: Schema
    ) -> None:
        """Return 404 when updating a nonexistent table."""
        payload = {
            "name": "ghost_table",
            "create": "CREATE TABLE ghost (id INT)",
            "keys": {},
            "schema_id": schema.id,
        }
        response = test_client.put("/tables/99999", json=payload)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_table_invalid_schema_id(
        self, test_client: TestClient, table: Table
    ) -> None:
        """Return 400 when schema_id references a nonexistent schema."""
        payload = {
            "name": table.name,
            "create": table.create,
            "keys": table.keys,
            "schema_id": 99999,
        }
        response = test_client.put(f"/tables/{table.id}", json=payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST


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
