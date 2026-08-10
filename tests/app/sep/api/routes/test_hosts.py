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

    def test_duplicate_inventory_addresses_keep_first_match(
        self,
        test_client: TestClient,
        mock_task_api_dep,
        mock_inventory_api_dep,
    ) -> None:
        """Keep the first inventory name when two records share an address.

        Pin the deduplication semantics inherited from
        ``address_to_name_index`` (first wins). The previous dict-comprehension
        implementation was "last wins"; switching to the shared helper aligns
        this route with ``resolve_executor_name_by_address`` so both call
        sites resolve a duplicated address to the same display name. Duplicate
        addresses are not expected in practice, but locking the choice in a
        test prevents an accidental revert.
        """
        mock_task_api_dep.get.return_value = {"nomad-1": "10.0.0.1"}
        mock_inventory_api_dep.get.return_value = {
            "items": [
                {"address": "10.0.0.1", "name": "db-primary"},
                {"address": "10.0.0.1", "name": "db-shadow"},
            ]
        }
        response = test_client.get("/api/sep/hosts/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {"id": "nomad-1", "name": "db-primary", "address": "10.0.0.1"},
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

    def test_tasks_failure_returns_502(
        self,
        test_client: TestClient,
        mock_task_api_dep,
        mock_inventory_api_dep,
    ) -> None:
        """Return ``502`` + ``{"detail": ...}`` when the Tasks API is unreachable.

        Catch the upstream ``HTTPException`` and re-raise as
        :class:`~app.core.exceptions.HTTPBadGatewayException`; the SEP exception
        handler turns it into a JSON ``502`` response that the React frontend
        surfaces through React Query's error state.
        """
        mock_task_api_dep.get.side_effect = HTTPBadGatewayException("tasks unreachable")
        mock_inventory_api_dep.get.return_value = {"items": []}
        response = test_client.get("/api/sep/hosts/")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json() == {"detail": "tasks unreachable"}

    def test_tasks_oserror_returns_502(
        self,
        test_client: TestClient,
        mock_task_api_dep,
        mock_inventory_api_dep,
    ) -> None:
        """Return ``502`` + ``{"detail": ...}`` when the Tasks API raises an OSError."""
        mock_task_api_dep.get.side_effect = OSError("connection refused")
        mock_inventory_api_dep.get.return_value = {"items": []}
        response = test_client.get("/api/sep/hosts/")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json() == {"detail": "connection refused"}


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

    def test_unauthenticated_unknown_sep_path_returns_json_404(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Return JSON 404 for unknown ``/api/sep/*`` paths even when unauthenticated.

        The 404 handler is unconditional now, so an unmatched path returns JSON
        regardless of whether the caller is authenticated.
        """
        response = unauthenticated_client.get(
            "/api/sep/does-not-exist/", follow_redirects=False
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()

    def test_authenticated_unknown_sep_path_returns_json_404(
        self, test_client: TestClient
    ) -> None:
        """Return JSON 404 for unknown ``/api/sep/*`` paths under an authenticated client."""
        response = test_client.get("/api/sep/does-not-exist/", follow_redirects=False)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()
