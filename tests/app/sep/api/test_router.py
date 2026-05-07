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

from app.sep.api.router import api_router, build_plugins_router, plugins_router
from app.sep.config import Plugin, sep_settings
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
        """Assert checksums and inventory plugin schema routes resolve on ``sep_app``.

        Both plugins mount under ``/api/plugins/{name}/schema`` on the composed
        application router.
        """
        api_plugin_paths = {
            route.path for route in sep_app.routes if hasattr(route, "path")
        }
        assert "/api/plugins/checksums/schema" in api_plugin_paths
        assert "/api/plugins/inventory/schema" in api_plugin_paths


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


class TestApiRouterConfigDrivenLoop:
    """Test the config-driven plugin mount loop (SEP-1109)."""

    def test_plugin_with_api_router_path_is_mounted(self) -> None:
        """Assert a plugin with ``api_router_path`` set produces mounted routes."""
        plugin = Plugin(
            name="Checksums",
            module_name="checksums",
            api_router_path="app.sep.plugins.checksums.api_routes.router",
        )
        router = build_plugins_router([plugin])
        paths = {r.path for r in router.routes if hasattr(r, "path")}
        assert any(p.startswith("/plugins/checksums/") for p in paths)

    def test_plugin_without_api_router_path_is_not_mounted(self) -> None:
        """Assert a plugin with ``api_router_path=None`` contributes no routes."""
        plugin = Plugin(
            name="Inventory",
            module_name="inventory",
            api_router_path=None,
        )
        router = build_plugins_router([plugin])
        assert router.routes == []

    def test_empty_plugins_iterable_produces_empty_router(self) -> None:
        """Assert no plugins → no plugin routes (only the prefix)."""
        router = build_plugins_router([])
        assert router.prefix == "/plugins"
        assert router.routes == []

    def test_mounted_plugin_routes_carry_module_basename_tag(self) -> None:
        """Assert each mounted plugin's routes carry ``tags=[module_basename]``."""
        plugin = Plugin(
            name="Dipper Data Collection",
            module_name="dipper",
            api_router_path="app.sep.plugins.dipper.api_routes.router",
        )
        router = build_plugins_router([plugin])
        tagged = [
            r.tags for r in router.routes if hasattr(r, "path") and "dipper" in r.path
        ]
        assert tagged
        assert all("dipper" in tags for tags in tagged)

    def test_invalid_api_router_path_module_raises(self) -> None:
        """Assert a non-importable module path fails fast at construction."""
        plugin = Plugin(
            name="Ghost",
            module_name="snippets",
            api_router_path="app.does.not.exist.router",
        )
        with pytest.raises(ImportError):
            build_plugins_router([plugin])

    def test_api_router_path_pointing_at_missing_attribute_raises(self) -> None:
        """Assert pointing at a missing attribute fails fast at construction."""
        plugin = Plugin(
            name="Ghost",
            module_name="snippets",
            api_router_path="app.sep.plugins.snippets.api_routes.does_not_exist",
        )
        with pytest.raises(AttributeError):
            build_plugins_router([plugin])

    def test_colon_syntax_in_api_router_path_is_rejected(self) -> None:
        """Assert colon-style ``module:attr`` paths are rejected.

        ``import_var`` uses ``rsplit('.', 1)`` so colon syntax leaves the
        module piece embedded in the attribute name and the import fails.
        """
        plugin = Plugin(
            name="Bad",
            module_name="checksums",
            api_router_path="app.sep.plugins.checksums.api_routes:router",
        )
        with pytest.raises((ImportError, AttributeError, ModuleNotFoundError)):
            build_plugins_router([plugin])

    def test_plugin_omitting_api_router_path_auto_derives_for_known_module(
        self,
    ) -> None:
        """Assert convention auto-derive sets ``api_router_path`` for built-ins."""
        for module, expected in (
            ("checksums", "app.sep.plugins.checksums.api_routes.router"),
            ("dipper", "app.sep.plugins.dipper.api_routes.router"),
            ("snippets", "app.sep.plugins.snippets.api_routes.router"),
        ):
            plugin = Plugin(name=module.title(), module_name=module)
            assert plugin.api_router_path == expected

    def test_plugin_omitting_api_router_path_stays_none_when_no_api_routes(
        self,
    ) -> None:
        """Assert convention is silent when the plugin ships no ``api_routes`` module."""
        plugin = Plugin(name="Archive", module_name="archives")
        assert plugin.api_router_path is None

    def test_explicit_null_api_router_path_opts_out(self) -> None:
        """Assert explicit ``null`` input wins over convention auto-derive."""
        plugin = Plugin.model_validate(
            {
                "name": "Checksums",
                "module_name": "checksums",
                "api_router_path": None,
            }
        )
        assert plugin.api_router_path is None

    def test_explicit_string_api_router_path_wins_over_convention(self) -> None:
        """Assert explicit string wins over the conventional path."""
        custom = "app.sep.plugins.dipper.api_routes.router"
        plugin = Plugin(
            name="Checksums",
            module_name="checksums",
            api_router_path=custom,
        )
        assert plugin.api_router_path == custom

    def test_legacy_yaml_override_without_api_router_path_still_mounts_builtin_apis(
        self,
    ) -> None:
        """Assert legacy operator overrides keep their JSON endpoints.

        Mimic a pre-SEP-1109 ``settings.yaml`` override that re-declares the
        three built-in plugins with only ``name`` / ``module_name`` /
        ``uri_path`` / ``css_class`` and no ``api_router_path``.
        """
        plugins = [
            Plugin(
                name="Snippet Manager",
                module_name="snippets",
                uri_path="/snippets",
                css_class="snippets",
            ),
            Plugin(
                name="Checksums",
                module_name="checksums",
                uri_path="/checksums",
                css_class="checksums",
            ),
            Plugin(
                name="Dipper Data Collection",
                module_name="dipper",
                uri_path="/dipper",
                css_class="dipper",
            ),
        ]
        router = build_plugins_router(plugins)
        paths = {r.path for r in router.routes if hasattr(r, "path")}
        assert any(p.startswith("/plugins/snippets/") for p in paths)
        assert any(p.startswith("/plugins/checksums/") for p in paths)
        assert any(p.startswith("/plugins/dipper/") for p in paths)

    def test_module_level_plugins_router_matches_settings(self) -> None:
        """Assert module-level ``plugins_router`` mirrors ``sep_settings.PLUGINS``."""
        expected_keys = {
            plugin.module_name.split(".")[-1]
            for plugin in sep_settings.PLUGINS
            if plugin.api_router_path is not None
        }
        seen_prefixes = {
            r.path.split("/")[2]
            for r in plugins_router.routes
            if hasattr(r, "path") and r.path.startswith("/plugins/")
        }
        assert expected_keys
        assert seen_prefixes == expected_keys


class TestApiRouterConfigDrivenLoopIntegration:
    """Integration tests against ``sep_app`` for runtime mount/no-mount behavior."""

    def test_sep_hosts_endpoint_unchanged(self) -> None:
        """Assert ``/api/sep/hosts`` is still mounted on ``sep_app``."""
        paths = {r.path for r in sep_app.routes if hasattr(r, "path")}
        assert any(p.startswith("/api/sep/hosts") for p in paths)

    def test_api_router_inherits_is_api_authenticated(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Assert plugin routes still 401 unauth — guard not bypassed by the loop."""
        response = unauthenticated_client.get(
            "/api/plugins/dipper/schema", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unmounted_plugin_returns_404(self, test_client: TestClient) -> None:
        """Assert a plugin key with no settings entry returns 404."""
        response = test_client.get("/api/plugins/not-a-real-plugin/schema")
        assert response.status_code == status.HTTP_404_NOT_FOUND
