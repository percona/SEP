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

from collections.abc import Iterator

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.sep.api._stub import router as stub_router
from app.sep.api.router import api_router, plugins_router
from app.sep.deps import IsApiAuthenticated
from app.sep.main import sep_app


@pytest.fixture
def unauthenticated_client() -> Iterator[TestClient]:
    """Yield a ``TestClient`` with ``sep_app`` dependency overrides cleared.

    Save and restore ``sep_app.dependency_overrides`` so the temporary removal
    of auth overrides does not leak into subsequent tests.
    """
    previous = sep_app.dependency_overrides
    sep_app.dependency_overrides = {}
    try:
        yield TestClient(sep_app, raise_server_exceptions=False)
    finally:
        sep_app.dependency_overrides = previous


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

    def test_stub_router_registered_under_plugins(self) -> None:
        """Assert the stub route is resolvable under ``/plugins/_stub``."""
        plugin_paths = {
            route.path for route in plugins_router.routes if hasattr(route, "path")
        }
        assert "/plugins/_stub/" in plugin_paths

    def test_stub_router_has_stub_tag(self) -> None:
        """Assert routes contributed by the stub sub-router expose the ``_stub`` tag."""
        stub_route_tags = [
            route.tags
            for route in plugins_router.routes
            if hasattr(route, "path") and "_stub" in route.path
        ]
        assert stub_route_tags
        assert all("_stub" in tags for tags in stub_route_tags)

    def test_plugins_router_included_via_api_router(self) -> None:
        """Assert every stub route resolves on ``sep_app`` under ``/api/plugins/``."""
        api_plugin_paths = {
            route.path for route in sep_app.routes if hasattr(route, "path")
        }
        assert "/api/plugins/_stub/" in api_plugin_paths

    def test_stub_router_module_exports_stub_endpoint(self) -> None:
        """Assert the isolated stub module exposes the ``GET /`` endpoint."""
        stub_paths = {
            route.path for route in stub_router.routes if hasattr(route, "path")
        }
        assert "/" in stub_paths


class TestApiRouterAuthenticated:
    """Test authenticated access to the shared API router."""

    def test_stub_endpoint_returns_ok(self, test_client: TestClient) -> None:
        """Assert an authenticated GET on the stub endpoint returns the JSON payload."""
        response = test_client.get("/api/plugins/_stub/")
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {"ok": True}

    def test_unknown_plugin_returns_json_404(self, test_client: TestClient) -> None:
        """Assert an authenticated GET on an unknown plugin returns JSON 404."""
        response = test_client.get("/api/plugins/does-not-exist/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()

    def test_unknown_subpath_under_stub_returns_json_404(
        self, test_client: TestClient
    ) -> None:
        """Assert an unknown sub-path under the stub returns JSON 404."""
        response = test_client.get("/api/plugins/_stub/nonexistent")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()


class TestApiRouterUnauthenticated:
    """Test unauthenticated access to the shared API router returns JSON 401."""

    def test_unauthenticated_stub_returns_json_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Assert unauth GET on the stub returns 401 JSON, not 303 redirect."""
        response = unauthenticated_client.get(
            "/api/plugins/_stub/", follow_redirects=False
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
