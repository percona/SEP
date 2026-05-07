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

"""Define tests for the shared SEP API router at ``/api/plugins/``."""

from fastapi import status
from fastapi.testclient import TestClient

from app.sep.api.router import api_router, plugins_router
from app.sep.deps import IsApiAuthenticated
from app.sep.main import sep_app


class TestApiRouterComposition:
    """Test the shape of the shared API router (prefixes, deps, inclusion)."""

    def test_api_router_prefix(self) -> None:
        """Assert the shared API router is mounted under ``/api``."""
        assert api_router.prefix == "/api"

    def test_api_router_declares_api_auth(self) -> None:
        """Assert ``IsApiAuthenticated`` is declared at router level."""
        assert IsApiAuthenticated in api_router.dependencies

    def test_plugins_router_prefix(self) -> None:
        """Assert the plugins sub-router carries the ``/plugins`` prefix."""
        assert plugins_router.prefix == "/plugins"

    def test_atw_router_registered_under_plugins(self) -> None:
        """Assert the ATW schema route is resolvable under ``/plugins/atw``."""
        plugin_paths = {
            route.path for route in plugins_router.routes if hasattr(route, "path")
        }
        assert "/plugins/atw/schema" in plugin_paths

    def test_checksums_router_registered_under_plugins(self) -> None:
        """Assert the checksums schema route is resolvable under ``/plugins/checksums``."""
        plugin_paths = {
            route.path for route in plugins_router.routes if hasattr(route, "path")
        }
        assert "/plugins/checksums/schema" in plugin_paths

    def test_checksums_router_has_checksums_tag(self) -> None:
        """Assert routes contributed by the checksums sub-router expose the ``checksums`` tag."""
        checksums_route_tags = [
            route.tags
            for route in plugins_router.routes
            if hasattr(route, "path") and "checksums" in route.path
        ]
        assert checksums_route_tags
        assert all("checksums" in tags for tags in checksums_route_tags)

    def test_plugins_router_included_via_api_router(self) -> None:
        """Assert every checksums route resolves on ``sep_app`` under ``/api/plugins/``."""
        api_plugin_paths = {
            route.path for route in sep_app.routes if hasattr(route, "path")
        }
        assert "/api/plugins/atw/schema" in api_plugin_paths
        assert "/api/plugins/checksums/schema" in api_plugin_paths


class TestApiRouterAuthenticated:
    """Test authenticated access to the shared API router."""

    def test_checksums_schema_endpoint_returns_ok(
        self, test_client: TestClient
    ) -> None:
        """Assert an authenticated GET on the checksums schema endpoint returns the schema."""
        response = test_client.get("/api/plugins/checksums/schema")
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["name"] == "checksums"

    def test_unknown_plugin_returns_json_404(self, test_client: TestClient) -> None:
        """Assert an authenticated GET on an unknown plugin returns JSON 404."""
        response = test_client.get("/api/plugins/does-not-exist/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()

    def test_unknown_nested_subpath_under_checksums_returns_json_404(
        self, test_client: TestClient
    ) -> None:
        """Assert a multi-segment path under the checksums plugin returns JSON 404.

        A single-segment path like ``/{task_name}`` is caught by the detail
        route, so use two segments to ensure no route matches.
        """
        response = test_client.get("/api/plugins/checksums/some/deeply/nested")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()


class TestApiRouterUnauthenticated:
    """Test unauthenticated access to the shared API router returns JSON 401."""

    def test_unauthenticated_checksums_schema_returns_json_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Assert unauth GET on the checksums schema returns 401 JSON, not 303 redirect."""
        response = unauthenticated_client.get(
            "/api/plugins/checksums/schema", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()

    def test_unauthenticated_unknown_plugin_returns_json_404(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Assert an unauth GET on an unknown plugin returns JSON 404 via the handler."""
        response = unauthenticated_client.get(
            "/api/plugins/does-not-exist/", follow_redirects=False
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()
