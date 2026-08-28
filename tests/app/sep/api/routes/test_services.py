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

"""Tests for the SEP services JSON API route at ``/api/sep/services/``."""

from datetime import datetime, UTC

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.pagination import MAX_PAGINATION_LIMIT


def _service_payload(service_id: int = 1, name: str = "svc1", type_: str = "mysql"):
    """Build a minimal inventory ``ServiceResponse`` dict for proxy mocks."""
    now = datetime.now(UTC).isoformat()
    return {
        "id": service_id,
        "created_at": now,
        "updated_at": now,
        "external_id": f"/service_id/{service_id}",
        "name": name,
        "type": type_,
        "port": 3306,
        "environment": None,
        "cluster": None,
        "replication_set": None,
        "custom_labels": None,
        "node_id": 1,
        "schemas": [],
        "node": {
            "id": 1,
            "created_at": now,
            "updated_at": now,
            "external_id": "/node_id/1",
            "source": "pmm",
            "name": "n1",
            "address": "127.0.0.1",
            "environment": None,
            "cluster": None,
        },
    }


class TestSepServicesEndpoint:
    """Tests for ``GET /api/sep/services/``."""

    def test_proxies_inventory_list(
        self,
        test_client: TestClient,
        mock_inventory_api_dep,
    ) -> None:
        """Return the paginated services payload returned by the inventory API."""
        mock_inventory_api_dep.get.return_value = {
            "items": [_service_payload()],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get("/api/sep/services/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "svc1"
        _, kwargs = mock_inventory_api_dep.get.call_args_list[0]
        assert kwargs["params"]["offset"] == 0
        assert kwargs["params"]["limit"] == 50  # noqa: PLR2004
        assert "service_type" not in kwargs["params"]

    def test_forwards_service_type_filter(
        self,
        test_client: TestClient,
        mock_inventory_api_dep,
    ) -> None:
        """The ``service_type`` query param is forwarded to the inventory API."""
        mock_inventory_api_dep.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get(
            "/api/sep/services/?service_type=mysql&offset=10&limit=5"
        )
        assert response.status_code == status.HTTP_200_OK
        _, kwargs = mock_inventory_api_dep.get.call_args_list[0]
        assert kwargs["params"] == {
            "offset": 10,
            "limit": 5,
            "service_type": "mysql",
        }

    @pytest.mark.parametrize(
        "query",
        ["offset=-1", "limit=0", "limit=-1", f"limit={MAX_PAGINATION_LIMIT + 1}"],
    )
    def test_rejects_negative_pagination(
        self,
        test_client: TestClient,
        mock_inventory_api_dep,
        query: str,
    ) -> None:
        """Invalid pagination values must be rejected with 422."""
        response = test_client.get(f"/api/sep/services/?{query}")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_inventory_api_dep.get.assert_not_called()
