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
