"""Define tests for inventory summary route."""

from starlette import status
from starlette.testclient import TestClient

from app.inventory.models import Table


class TestGetSummaryInventory:
    """Test the GET /summary/ endpoint."""

    def test_summary_empty(self, test_client: TestClient) -> None:
        """Return all zero counts when the database is empty."""
        response = test_client.get("/summary/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "nodes": 0,
            "services": 0,
            "schemas": 0,
            "tables": 0,
        }

    def test_summary_populated(self, test_client: TestClient, table: Table) -> None:
        """Return correct counts when inventory entities exist."""
        response = test_client.get("/summary/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["nodes"] == 1
        assert data["services"] == 1
        assert data["schemas"] == 1
        assert data["tables"] == 1
