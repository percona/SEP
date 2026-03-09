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

"""Define tests for SEP inventory API proxy routes."""

from unittest.mock import AsyncMock

from fastapi import HTTPException
from starlette import status
from starlette.testclient import TestClient


class TestListSchemas:
    """Test GET /inventory-api/services/{service_id}/schemas endpoint."""

    def test_list_schemas(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Return schemas for a service."""
        mock_inventory_api_dep.get.return_value = [
            {"id": 1, "name": "db1", "service_id": 10},
            {"id": 2, "name": "db2", "service_id": 10},
        ]
        response = test_client.get("/inventory-api/services/10/schemas")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data == [{"id": 1, "name": "db1"}, {"id": 2, "name": "db2"}]

    def test_list_schemas_with_search(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Pass search parameter through to inventory API."""
        mock_inventory_api_dep.get.return_value = [
            {"id": 1, "name": "mydb", "service_id": 10},
        ]
        response = test_client.get(
            "/inventory-api/services/10/schemas", params={"search": "my"}
        )
        assert response.status_code == status.HTTP_200_OK
        mock_inventory_api_dep.get.assert_called_once_with(
            "/services/10/schemas/", params={"search": "my"}
        )

    def test_list_schemas_empty(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Return empty list when service has no schemas."""
        mock_inventory_api_dep.get.return_value = []
        response = test_client.get("/inventory-api/services/10/schemas")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_schemas_service_not_found(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Return empty list when inventory API raises HTTPException."""
        mock_inventory_api_dep.get.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not Found"
        )
        response = test_client.get("/inventory-api/services/9999/schemas")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []


class TestListTables:
    """Test GET /inventory-api/schemas/{schema_id}/tables endpoint."""

    def test_list_tables(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Return tables for a schema."""
        mock_inventory_api_dep.get.return_value = [
            {"id": 1, "name": "users", "schema_id": 5},
            {"id": 2, "name": "orders", "schema_id": 5},
        ]
        response = test_client.get("/inventory-api/schemas/5/tables")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data == [{"id": 1, "name": "users"}, {"id": 2, "name": "orders"}]

    def test_list_tables_with_search(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Pass search parameter through to inventory API."""
        mock_inventory_api_dep.get.return_value = [
            {"id": 1, "name": "users", "schema_id": 5},
        ]
        response = test_client.get(
            "/inventory-api/schemas/5/tables", params={"search": "user"}
        )
        assert response.status_code == status.HTTP_200_OK
        mock_inventory_api_dep.get.assert_called_once_with(
            "/schemas/5/tables/", params={"search": "user"}
        )

    def test_list_tables_schema_not_found(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Return empty list when inventory API raises HTTPException."""
        mock_inventory_api_dep.get.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not Found"
        )
        response = test_client.get("/inventory-api/schemas/9999/tables")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
