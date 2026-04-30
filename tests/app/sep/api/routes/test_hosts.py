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

"""Tests for the SEP hosts JSON API route at ``/api/sep/hosts/``."""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.exceptions import HTTPBadGatewayException
from app.sep.main import sep_app


class TestSepHostsEndpoint:
    """Tests for ``GET /api/sep/hosts/`` happy-path and edge cases."""

    def test_returns_hosts_with_inventory_display_names_sorted(
        self,
        test_client: TestClient,
        mock_task_api_dep,
        mock_inventory_api_dep,
    ) -> None:
        """Return hosts merged with inventory names, sorted by case-folded name."""
        mock_task_api_dep.get.return_value = {
            "nomad-1": "10.0.0.1",
            "nomad-2": "10.0.0.2",
        }
        mock_inventory_api_dep.get.return_value = {
            "items": [
                {"address": "10.0.0.1", "name": "db-mysql-prod-01"},
                {"address": "10.0.0.2", "name": "db-mysql-prod-02"},
            ]
        }
        response = test_client.get("/api/sep/hosts/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {"id": "nomad-1", "name": "db-mysql-prod-01", "address": "10.0.0.1"},
            {"id": "nomad-2", "name": "db-mysql-prod-02", "address": "10.0.0.2"},
        ]

    def test_falls_back_to_node_name_when_inventory_match_missing(
        self,
        test_client: TestClient,
        mock_task_api_dep,
        mock_inventory_api_dep,
    ) -> None:
        """Return raw node names for hosts with no inventory match."""
        mock_task_api_dep.get.return_value = {
            "nomad-1": "10.0.0.1",
            "nomad-2": "10.0.0.2",
        }
        mock_inventory_api_dep.get.return_value = {
            "items": [
                {"address": "10.0.0.1", "name": "db-mysql-prod-01"},
            ]
        }
        response = test_client.get("/api/sep/hosts/")
        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert {host["id"] for host in payload} == {"nomad-1", "nomad-2"}
        names_by_id = {host["id"]: host["name"] for host in payload}
        assert names_by_id["nomad-1"] == "db-mysql-prod-01"
        assert names_by_id["nomad-2"] == "nomad-2"

    def test_extra_inventory_nodes_are_ignored(
        self,
        test_client: TestClient,
        mock_task_api_dep,
        mock_inventory_api_dep,
    ) -> None:
        """Drop inventory nodes whose address is not present in the executor list."""
        mock_task_api_dep.get.return_value = {"nomad-1": "10.0.0.1"}
        mock_inventory_api_dep.get.return_value = {
            "items": [
                {"address": "10.0.0.1", "name": "db-mysql-prod-01"},
                {"address": "10.0.0.99", "name": "ghost-node"},
            ]
        }
        response = test_client.get("/api/sep/hosts/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {"id": "nomad-1", "name": "db-mysql-prod-01", "address": "10.0.0.1"},
        ]

    def test_inventory_failure_returns_raw_node_names(
        self,
        test_client: TestClient,
        mock_task_api_dep,
        mock_inventory_api_dep,
    ) -> None:
        """Degrade gracefully when the Inventory API rejects the request."""
        mock_task_api_dep.get.return_value = {"nomad-1": "10.0.0.1"}
        mock_inventory_api_dep.get.side_effect = HTTPBadGatewayException(
            "inventory unreachable"
        )
        response = test_client.get("/api/sep/hosts/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {"id": "nomad-1", "name": "nomad-1", "address": "10.0.0.1"},
        ]

    def test_empty_executor_list_returns_empty_response(
        self,
        test_client: TestClient,
        mock_task_api_dep,
        mock_inventory_api_dep,
    ) -> None:
        """Return an empty list when the executor reports no hosts."""
        mock_task_api_dep.get.return_value = {}
        mock_inventory_api_dep.get.return_value = {"items": []}
        response = test_client.get("/api/sep/hosts/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_tasks_failure_returns_empty_list(
        self,
        test_client: TestClient,
        mock_task_api_dep,
        mock_inventory_api_dep,
    ) -> None:
        """Return ``200 []`` when the Tasks API is unreachable.

        Catch the upstream ``HTTPException`` and degrade to an empty list so
        the frontend can render "No hosts available" rather than a hard
        error. Also attach the ``X-Sep-Hosts-Upstream-Error`` header carrying
        the upstream detail so the React shell can raise a notification
        without breaking the ``200 []`` contract.
        """
        mock_task_api_dep.get.side_effect = HTTPBadGatewayException("tasks unreachable")
        mock_inventory_api_dep.get.return_value = {"items": []}
        response = test_client.get("/api/sep/hosts/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        assert response.headers["X-Sep-Hosts-Upstream-Error"] == "tasks unreachable"


class TestSepHostsAuth:
    """Tests for ``/api/sep/hosts/`` authentication enforcement."""

    @pytest.fixture
    def unauthenticated_client(self) -> TestClient:
        """Yield a TestClient with no auth dependency overrides applied."""
        previous = sep_app.dependency_overrides
        sep_app.dependency_overrides = {}
        try:
            yield TestClient(sep_app, raise_server_exceptions=False)
        finally:
            sep_app.dependency_overrides = previous

    def test_unauthenticated_returns_json_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Reject anonymous requests with a JSON 401 response (not an HTML redirect)."""
        response = unauthenticated_client.get("/api/sep/hosts/", follow_redirects=False)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()
