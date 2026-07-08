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

"""Tests for SEP inventory selector JSON API routes under ``/api/sep/``."""

from unittest.mock import AsyncMock

from fastapi import HTTPException
from starlette import status
from starlette.testclient import TestClient

from app.core.exceptions import HTTPNotFoundException, HTTPServiceUnavailableException
from app.core.pagination import MAX_PAGINATION_LIMIT


class TestSepServiceSchemasEndpoint:
    """Tests for ``GET /api/sep/services/{service_id}/schemas``."""

    def test_list_schemas(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Return schemas for a service."""
        mock_inventory_api_dep.get.return_value = {
            "items": [
                {"id": 1, "name": "db1", "service_id": 10},
                {"id": 2, "name": "db2", "service_id": 10},
            ],
            "total": 2,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get("/api/sep/services/10/schemas")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [{"id": 1, "name": "db1"}, {"id": 2, "name": "db2"}]

    def test_list_schemas_with_search(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Pass search parameter through to inventory API."""
        mock_inventory_api_dep.get.return_value = {
            "items": [{"id": 1, "name": "mydb", "service_id": 10}],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get(
            "/api/sep/services/10/schemas", params={"search": "my"}
        )
        assert response.status_code == status.HTTP_200_OK
        mock_inventory_api_dep.get.assert_called_once_with(
            "/services/10/schemas/",
            params={"offset": 0, "limit": MAX_PAGINATION_LIMIT, "search": "my"},
        )

    def test_list_schemas_empty_on_404(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Return empty list when inventory responds with 404."""
        mock_inventory_api_dep.get.side_effect = HTTPNotFoundException(
            detail="Not Found"
        )
        response = test_client.get("/api/sep/services/9999/schemas")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_schemas_propagates_non_404_inventory_error(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Propagate auth and server errors instead of masking as empty list."""
        mock_inventory_api_dep.get.side_effect = HTTPServiceUnavailableException(
            detail="Inventory unavailable",
        )
        response = test_client.get("/api/sep/services/10/schemas")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_list_schemas_empty_when_upstream_returns_none(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Return empty list when inventory returns a non-paginated null payload."""
        mock_inventory_api_dep.get.return_value = None
        response = test_client.get("/api/sep/services/10/schemas")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []


class TestSepSchemaTablesEndpoint:
    """Tests for ``GET /api/sep/schemas/{schema_id}/tables``."""

    def test_list_tables(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Return tables for a schema."""
        mock_inventory_api_dep.get.return_value = {
            "items": [
                {"id": 1, "name": "users", "schema_id": 5},
                {"id": 2, "name": "orders", "schema_id": 5},
            ],
            "total": 2,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get("/api/sep/schemas/5/tables")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {"id": 1, "name": "users"},
            {"id": 2, "name": "orders"},
        ]

    def test_list_tables_with_search(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Pass search parameter through to inventory API."""
        mock_inventory_api_dep.get.return_value = {
            "items": [{"id": 1, "name": "users", "schema_id": 5}],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get(
            "/api/sep/schemas/5/tables", params={"search": "user"}
        )
        assert response.status_code == status.HTTP_200_OK
        mock_inventory_api_dep.get.assert_called_once_with(
            "/schemas/5/tables/",
            params={"offset": 0, "limit": MAX_PAGINATION_LIMIT, "search": "user"},
        )

    def test_list_tables_empty_on_404(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Return empty list when inventory responds with 404."""
        mock_inventory_api_dep.get.side_effect = HTTPNotFoundException(
            detail="Not Found"
        )
        response = test_client.get("/api/sep/schemas/9999/tables")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_tables_propagates_non_404_inventory_error(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Propagate auth and server errors instead of masking as empty list."""
        mock_inventory_api_dep.get.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
        response = test_client.get("/api/sep/schemas/5/tables")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_tables_empty_when_upstream_returns_empty_object(
        self, test_client: TestClient, mock_inventory_api_dep: AsyncMock
    ) -> None:
        """Return empty list when inventory returns a dict without items."""
        mock_inventory_api_dep.get.return_value = {}
        response = test_client.get("/api/sep/schemas/5/tables")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
