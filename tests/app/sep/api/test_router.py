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

"""Define tests for the shared SEP API router at ``/api/apps/``."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, status
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytest_mock import MockerFixture
from starlette.routing import Match

from app.sep.api.router import api_router, apps_router, build_apps_router
from app.sep.apps.framework.registry import build_app_registry
from app.sep.config import App, sep_settings
from app.sep.deps import (
    BEARER_REQUIRED_DETAIL,
    get_current_user,
    IsApiAuthenticated,
    require_bearer_for_unsafe_methods,
)
from app.sep.main import sep_app


class TestApiRouterComposition:
    """Test the shape of the shared API router (prefixes, deps, inclusion)."""

    def test_api_router_prefix(self) -> None:
        """Assert the shared API router is mounted under ``/api``."""
        assert api_router.prefix == "/api"

    def test_api_router_declares_api_auth(self) -> None:
        """Assert ``IsApiAuthenticated`` is declared at router level."""
        assert IsApiAuthenticated in api_router.dependencies

    def test_apps_router_prefix(self) -> None:
        """Assert the plugins sub-router carries the ``/apps`` prefix."""
        assert apps_router.prefix == "/apps"

    def test_atw_router_registered_under_plugins(self) -> None:
        """Assert the ATW schema route is resolvable under ``/apps/atw``."""
        plugin_paths = {
            route.path for route in apps_router.routes if hasattr(route, "path")
        }
        assert "/apps/atw/schema" in plugin_paths

    def test_checksums_router_registered_under_plugins(self) -> None:
        """Assert the checksums schema route is resolvable under ``/apps/checksums``."""
        plugin_paths = {
            route.path for route in apps_router.routes if hasattr(route, "path")
        }
        assert "/apps/checksums/schema" in plugin_paths

    def test_checksums_router_has_checksums_tag(self) -> None:
        """Assert routes contributed by the checksums sub-router expose the ``checksums`` tag."""
        checksums_route_tags = [
            route.tags
            for route in apps_router.routes
            if hasattr(route, "path") and "checksums" in route.path
        ]
        assert checksums_route_tags
        assert all("checksums" in tags for tags in checksums_route_tags)

    def test_apps_router_included_via_api_router(self) -> None:
        """Assert checksums and inventory plugin schema routes resolve on ``sep_app``.

        Both plugins mount under ``/api/apps/{name}/schema`` on the composed
        application router.
        """
        api_plugin_paths = {
            route.path for route in sep_app.routes if hasattr(route, "path")
        }
        assert "/api/apps/atw/schema" in api_plugin_paths
        assert "/api/apps/checksums/schema" in api_plugin_paths
        assert "/api/apps/inventory/schema" in api_plugin_paths

    def test_legacy_plugins_prefix_removed_from_route_table(self) -> None:
        """Assert no composed route remains under the retired ``/api/plugins`` prefix."""
        api_paths = {route.path for route in sep_app.routes if hasattr(route, "path")}
        assert not any(path.startswith("/api/plugins") for path in api_paths)


class TestApiRouterAuthenticated:
    """Test authenticated access to the shared API router."""

    def test_checksums_schema_endpoint_returns_ok(
        self, test_client: TestClient
    ) -> None:
        """Assert an authenticated GET on the checksums schema endpoint returns the schema."""
        response = test_client.get("/api/apps/checksums/schema")
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["name"] == "checksums"

    def test_unknown_plugin_returns_json_404(self, test_client: TestClient) -> None:
        """Assert an authenticated GET on an unknown plugin returns JSON 404."""
        response = test_client.get("/api/apps/does-not-exist/")
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
        response = test_client.get("/api/apps/checksums/some/deeply/nested")
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
            "/api/apps/checksums/schema", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()

    def test_unauthenticated_unknown_plugin_returns_json_404(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Assert an unauth GET on an unknown plugin returns JSON 404 via the handler."""
        response = unauthenticated_client.get(
            "/api/apps/does-not-exist/", follow_redirects=False
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()


@pytest.fixture
def cookie_only_client(regular_user):
    """Return an authenticated TestClient with the Bearer gate left intact.

    Overrides ``get_current_user`` so the request passes authentication, but
    deliberately leaves ``require_bearer_for_unsafe_methods`` unmocked so the
    Bearer gate fires for mutating methods.
    """
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


class TestPluginBearerGate:
    """Exercise the framework-level Bearer gate on /api/apps/* mutations."""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", "/api/apps/snippets/refresh"),
            ("PUT", "/api/apps/snippets/snippet/approval"),
            ("PATCH", "/api/apps/snippets/approvals"),
            ("DELETE", "/api/apps/snippets/snippet/approval"),
            ("POST", "/api/apps/inventory/sync/"),
            ("POST", "/api/apps/dipper/"),
            ("POST", "/api/apps/checksums/"),
            ("DELETE", "/api/apps/checksums/some-task"),
        ],
    )
    def test_cookie_only_mutation_is_rejected_with_401(
        self, cookie_only_client: TestClient, method: str, path: str
    ) -> None:
        """Reject cookie-authenticated JSON mutations under /api/apps/* with 401."""
        response = cookie_only_client.request(method, path, json={})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL

    def test_cookie_only_get_passes_bearer_gate(
        self, cookie_only_client: TestClient
    ) -> None:
        """Allow a cookie-authenticated GET on /api/apps/* through the Bearer gate."""
        response = cookie_only_client.get("/api/apps/checksums/schema")
        assert response.status_code != status.HTTP_401_UNAUTHORIZED

    def test_bearer_mutation_passes_bearer_gate(
        self, cookie_only_client: TestClient
    ) -> None:
        """A Bearer header on a mutation bypasses the framework Bearer gate.

        The downstream route may still 422/404/etc., but the response must
        not be the framework Bearer-gate 401.
        """
        response = cookie_only_client.post(
            "/api/apps/snippets/refresh",
            json={},
            headers={"Authorization": "Bearer test-token"},
        )
        if response.status_code == status.HTTP_401_UNAUTHORIZED:
            assert response.json().get("detail") != BEARER_REQUIRED_DETAIL

    def test_malformed_json_cookie_only_still_401_before_body_parse(
        self, cookie_only_client: TestClient
    ) -> None:
        """The Bearer gate fires before request-body validation.

        Sending malformed JSON with cookie auth must return the Bearer-gate
        401, not a 422 from body parsing.
        """
        response = cookie_only_client.post(
            "/api/apps/snippets/refresh",
            content=b"{not-json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL

    def test_head_method_passes_bearer_gate(
        self, cookie_only_client: TestClient
    ) -> None:
        """HEAD requests are treated as safe and not Bearer-gated."""
        response = cookie_only_client.head("/api/apps/checksums/schema")
        assert response.status_code != status.HTTP_401_UNAUTHORIZED

    def test_options_method_passes_bearer_gate(
        self, cookie_only_client: TestClient
    ) -> None:
        """OPTIONS (CORS preflight) requests are not Bearer-gated."""
        response = cookie_only_client.options("/api/apps/checksums/schema")
        assert response.status_code != status.HTTP_401_UNAUTHORIZED

    def test_bearer_gate_is_hoisted_to_the_api_router(self) -> None:
        """Check the Bearer gate covers the whole ``/api`` tree, not just ``/apps``.

        With cookie authentication gone, every ``/api`` caller presents a Bearer
        token, so the gate is hoisted to ``api_router`` and every mutating route
        inherits it uniformly rather than per-router. The gate is method-scoped,
        so reads are unaffected; ``test_api_sep_get_routes_are_not_bearer_gated``
        pins that half.
        """
        plugin_deps = [dep.dependency for dep in apps_router.dependencies]
        api_deps = [dep.dependency for dep in api_router.dependencies]
        assert require_bearer_for_unsafe_methods in api_deps
        # Kept on apps_router too: FastAPI caches identical ``Depends`` objects
        # per request, so the duplicate registration executes once.
        assert require_bearer_for_unsafe_methods in plugin_deps

    def test_api_sep_get_routes_are_not_bearer_gated(
        self,
        cookie_only_client: TestClient,
        mock_task_api_dep,
        mock_inventory_api_dep,
        mocker,
    ) -> None:
        """Serve a GET on /api/sep/* without tripping the Bearer gate.

        Regression guard for the hoist: the gate is method-scoped, so reads
        must still succeed (200) even without a Bearer header on the request
        itself. Upstream Tasks/Inventory and the SEP snippets count
        are stubbed so the dashboard returns a deterministic payload
        independent of any persisted snippet rows in the local SEP DB.
        """
        mock_inventory_api_dep.get.return_value = {"nodes": 0}
        mock_task_api_dep.get.side_effect = [{"total": 0}, []]
        mocker.patch(
            "app.sep.api.routes.dashboard.SnippetManager.count",
            new_callable=AsyncMock,
            return_value=0,
        )
        response = cookie_only_client.get("/api/sep/dashboard/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["nodes"] == 0
        assert body["tasks"] == 0
        assert body["targets"] == 0
        # Snippet count is DB-backed and not mocked in this bearer-gate test.
        assert isinstance(body["snippets"], int)
        assert body["snippets"] >= 0

    @pytest.mark.parametrize(
        "method",
        ["POST", "PUT", "PATCH", "DELETE"],
    )
    def test_all_unsafe_methods_return_same_detail_string(
        self, cookie_only_client: TestClient, method: str
    ) -> None:
        """Every mutating method returns the exact same path-agnostic detail string.

        Pins that the 401 body never leaks the request's method, path, or any
        other ambient state. ``snippets/refresh`` accepts POST and
        snippets-approval declares PUT/PATCH/DELETE — assert the detail only
        when the gate actually fires (status 401), so method-mismatch responses
        (405) are skipped without false-failing the test.
        """
        response = cookie_only_client.request(
            method, "/api/apps/snippets/snippet/approval", json={}
        )
        if response.status_code == status.HTTP_401_UNAUTHORIZED:
            assert response.json()["detail"] == BEARER_REQUIRED_DETAIL

    def test_detail_string_is_path_agnostic(
        self, cookie_only_client: TestClient
    ) -> None:
        """The 401 detail is byte-identical across two unrelated plugin paths.

        Regression guard for the PR-body promise that ``BEARER_REQUIRED_DETAIL``
        is a single, path-agnostic constant — no f-string sneaks the plugin
        name or route into the response body.
        """
        snippets_resp = cookie_only_client.post("/api/apps/snippets/refresh", json={})
        checksums_resp = cookie_only_client.post("/api/apps/checksums/", json={})
        assert snippets_resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert checksums_resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert (
            snippets_resp.json()["detail"]
            == checksums_resp.json()["detail"]
            == BEARER_REQUIRED_DETAIL
        )

    def test_405_when_method_not_supported_does_not_leak_bearer_detail(
        self, cookie_only_client: TestClient
    ) -> None:
        """A method-mismatch response under cookie-only auth is a vanilla 405.

        Documents the trade-off of mounting the gate at router level: deps run
        per-route after method resolution, so a wrong method on an existing
        path returns 405 (not 401). The response body must not echo
        ``BEARER_REQUIRED_DETAIL`` — that would imply the gate fired when it
        did not. Asserting "neither 200 nor leaked-detail" is the contract.
        """
        response = cookie_only_client.request(
            "PATCH", "/api/apps/snippets/refresh", json={}
        )
        assert response.status_code != status.HTTP_200_OK
        body = response.json() if response.content else {}
        assert body.get("detail") != BEARER_REQUIRED_DETAIL

    def test_404_for_unknown_plugin_path_does_not_leak_bearer_detail(
        self, cookie_only_client: TestClient
    ) -> None:
        """Cookie-only POST on an unknown sub-path returns 404 with no Bearer detail.

        Same path-existence trade-off as the 405 case: router-level deps don't
        fire when no route matches, so the response is 404. Crucially the body
        must NOT carry ``BEARER_REQUIRED_DETAIL`` — leaking it would imply the
        path exists but is bearer-gated, the inverse of what 404 should signal.
        """
        response = cookie_only_client.post("/api/apps/does-not-exist/foo", json={})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        body = response.json() if response.content else {}
        assert body.get("detail") != BEARER_REQUIRED_DETAIL

    def test_trace_method_on_existing_path_does_not_succeed(
        self, cookie_only_client: TestClient
    ) -> None:
        """``TRACE`` on an existing plugin path is never 200 under cookie-only auth.

        Documents that the safe-method whitelist is GET/HEAD/OPTIONS only —
        TRACE is excluded both because no route declares it (so the response is
        405) and because the gate would 401 it if a future route did. Either
        outcome must not be 200.
        """
        response = cookie_only_client.request("TRACE", "/api/apps/checksums/schema")
        assert response.status_code != status.HTTP_200_OK


def _force_legacy_synthesis(
    mocker: MockerFixture, *, stub_router: bool = False
) -> None:
    """Drive ``build_app_registry`` down the legacy-synthesis path.

    Every shipped plugin now exports an ``app`` definition, so the
    ``api_router_path``-driven synthesis is exercised against a module that
    exports no ``app``. When ``stub_router`` is set, the convention router import
    is stubbed so synthesis can complete past a ``None``/empty ``api_router_path``.
    """
    mocker.patch(
        "app.sep.apps.framework.registry.import_module",
        return_value=SimpleNamespace(),
    )
    if stub_router:
        mocker.patch(
            "app.sep.apps.framework.registry.import_var",
            return_value=APIRouter(),
        )


class TestApiRouterConfigDrivenLoop:
    """Test the config-driven plugin mount loop."""

    def test_plugin_with_api_router_path_is_mounted(self) -> None:
        """Assert a plugin with ``api_router_path`` set produces mounted routes."""
        plugin = App(
            name="Alters",
            module_name="alters",
            api_router_path="app.sep.apps.alters.api_routes.router",
        )
        router = build_apps_router(build_app_registry([plugin]))
        paths = {r.path for r in router.routes if hasattr(r, "path")}
        assert any(p.startswith("/apps/alters/") for p in paths)

    def test_plugin_without_api_router_path_is_not_mounted(
        self, mocker: MockerFixture
    ) -> None:
        """Assert a plugin with ``api_router_path=None`` contributes no routes."""
        _force_legacy_synthesis(mocker, stub_router=True)
        plugin = App(
            name="Alters",
            module_name="alters",
            api_router_path=None,
        )
        router = build_apps_router(build_app_registry([plugin]))
        assert router.routes == []

    def test_empty_plugins_iterable_produces_empty_router(self) -> None:
        """Assert no plugins → no plugin routes (only the prefix)."""
        router = build_apps_router(build_app_registry([]))
        assert router.prefix == "/apps"
        assert router.routes == []

    def test_mounted_plugin_routes_carry_module_basename_tag(self) -> None:
        """Assert each mounted plugin's routes carry ``tags=[module_basename]``."""
        plugin = App(
            name="Alters",
            module_name="alters",
            api_router_path="app.sep.apps.alters.api_routes.router",
        )
        router = build_apps_router(build_app_registry([plugin]))
        tagged = [
            r.tags for r in router.routes if hasattr(r, "path") and "alters" in r.path
        ]
        assert tagged
        assert all("alters" in tags for tags in tagged)

    def test_invalid_api_router_path_module_raises(self) -> None:
        """Assert a non-importable module path fails fast at App construction.

        With ``api_router_path`` typed as ``StrImportableAttribute | None``,
        Pydantic validates the module component at model construction time so
        the error surfaces before ``build_apps_router`` is ever called.
        """
        with pytest.raises(ValidationError):
            App(
                name="Ghost",
                module_name="snippets",
                api_router_path="app.does.not.exist.router",
            )

    def test_api_router_path_pointing_at_missing_attribute_raises(
        self, mocker: MockerFixture
    ) -> None:
        """Assert pointing at a missing attribute fails fast at construction."""
        _force_legacy_synthesis(mocker)
        plugin = App(
            name="Ghost",
            module_name="alters",
            api_router_path="app.sep.apps.alters.api_routes.does_not_exist",
        )
        with pytest.raises(AttributeError):
            build_apps_router(build_app_registry([plugin]))

    def test_colon_syntax_in_api_router_path_is_rejected(
        self, mocker: MockerFixture
    ) -> None:
        """Assert colon-style ``module:attr`` paths are rejected.

        ``import_var`` uses ``rsplit('.', 1)`` so colon syntax leaves the
        module piece embedded in the attribute name and the import fails.
        """
        _force_legacy_synthesis(mocker)
        plugin = App(
            name="Bad",
            module_name="alters",
            api_router_path="app.sep.apps.alters.api_routes:router",
        )
        with pytest.raises((ImportError, AttributeError, ModuleNotFoundError)):
            build_apps_router(build_app_registry([plugin]))

    def test_plugin_omitting_api_router_path_auto_derives_for_known_module(
        self,
    ) -> None:
        """Assert convention auto-derive sets ``api_router_path`` for built-ins."""
        for module, expected in (("dipper", "app.sep.apps.dipper.api_routes.router"),):
            plugin = App(name=module.title(), module_name=module)
            assert plugin.api_router_path == expected

    def test_plugin_omitting_api_router_path_auto_derives_for_alters(
        self,
    ) -> None:
        """Assert convention derives ``api_router_path`` once alters ships API routes."""
        plugin = App(name="Alters", module_name="alters")
        assert plugin.api_router_path == "app.sep.apps.alters.api_routes.router"

    def test_explicit_null_api_router_path_opts_out(self) -> None:
        """Assert explicit ``null`` input wins over convention auto-derive."""
        plugin = App.model_validate(
            {
                "name": "Checksums",
                "module_name": "checksums",
                "api_router_path": None,
            }
        )
        assert plugin.api_router_path is None

    def test_explicit_string_api_router_path_wins_over_convention(self) -> None:
        """Assert explicit string wins over the conventional path."""
        custom = "app.sep.apps.dipper.api_routes.router"
        plugin = App(
            name="Checksums",
            module_name="checksums",
            api_router_path=custom,
        )
        assert plugin.api_router_path == custom

    def test_legacy_yaml_override_without_api_router_path_still_mounts_builtin_apis(
        self,
    ) -> None:
        """Assert legacy operator overrides keep their JSON endpoints.

        Mimic a legacy ``settings.yaml`` override that re-declares the
        three built-in plugins with only ``name`` / ``module_name`` /
        ``uri_path`` / ``css_class`` and no ``api_router_path``.
        """
        plugins = [
            App(
                name="Snippet Manager",
                module_name="snippets",
                uri_path="/snippets",
                css_class="snippets",
            ),
            App(
                name="Checksums",
                module_name="checksums",
                uri_path="/checksums",
                css_class="checksums",
            ),
            App(
                name="Dipper Data Collection",
                module_name="dipper",
                uri_path="/dipper",
                css_class="dipper",
            ),
        ]
        router = build_apps_router(build_app_registry(plugins))
        paths = {r.path for r in router.routes if hasattr(r, "path")}
        assert any(p.startswith("/apps/snippets/") for p in paths)
        assert any(p.startswith("/apps/checksums/") for p in paths)
        assert any(p.startswith("/apps/dipper/") for p in paths)

    def test_build_apps_router_skips_empty_string_path(
        self, mocker: MockerFixture
    ) -> None:
        """Assert an empty-string ``api_router_path`` is treated as no-mount.

        Defense-in-depth: even if a falsy non-None value reaches the loop
        (e.g. programmatic construction bypassing Pydantic), no routes are
        mounted and no confusing ``ValueError`` is raised by ``import_var``.
        """
        _force_legacy_synthesis(mocker, stub_router=True)
        plugin = App.model_construct(
            name="Ghost",
            module_name="app.sep.apps.alters",
            api_router_path="",
        )
        router = build_apps_router(build_app_registry([plugin]))
        assert router.routes == []

    def test_build_apps_router_raises_type_error_for_non_router(
        self, mocker: MockerFixture
    ) -> None:
        """Assert importing a non-``APIRouter`` attribute raises ``TypeError``.

        The error must identify the offending plugin key and path so operators
        can diagnose YAML misconfigurations without reading tracebacks from
        ``include_router``.
        """
        _force_legacy_synthesis(mocker)
        plugin = App(
            name="Alters",
            module_name="alters",
            api_router_path="app.sep.config.App",
        )
        with pytest.raises(TypeError, match="alters"):
            build_apps_router(build_app_registry([plugin]))

    def test_plugin_api_router_path_rejects_bad_module_at_parse(self) -> None:
        """Assert an explicit ``api_router_path`` with a non-importable module raises ``ValidationError``.

        Errors should be caught at settings construction, not at application
        startup when ``build_apps_router`` is first called.
        """
        with pytest.raises(ValidationError):
            App(
                name="Ghost",
                module_name="checksums",
                api_router_path="not.a.real.module.router",
            )

    def test_module_level_apps_router_matches_settings(self) -> None:
        """Assert module-level ``apps_router`` mirrors ``sep_settings.APPS``."""
        expected_keys = {
            app.key
            for app in build_app_registry(sep_settings.APPS)
            if app.api_router is not None
        }

        def owning_key(route_path: str) -> str | None:
            rest = route_path.removeprefix("/apps/")
            candidates = [
                key
                for key in expected_keys
                if rest == key or rest.startswith(key + "/")
            ]
            return max(candidates, key=len) if candidates else None

        seen_prefixes = {
            owning_key(r.path)
            for r in apps_router.routes
            if hasattr(r, "path") and r.path.startswith("/apps/")
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
            "/api/apps/dipper/schema", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unmounted_plugin_returns_404(self, test_client: TestClient) -> None:
        """Assert a plugin key with no settings entry returns 404."""
        response = test_client.get("/api/apps/not-a-real-plugin/schema")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize(
        ("method", "path", "expected_prefix"),
        [
            (
                "GET",
                "/api/apps/mysql_backups/restore/",
                "/api/apps/mysql_backups/restore",
            ),
            (
                "POST",
                "/api/apps/mysql_backups/restore/",
                "/api/apps/mysql_backups/restore",
            ),
            (
                "GET",
                "/api/apps/mysql_backups/restore/schema",
                "/api/apps/mysql_backups/restore",
            ),
            (
                "GET",
                "/api/apps/mysql_backups/restore/some-task",
                "/api/apps/mysql_backups/restore",
            ),
            (
                "GET",
                "/api/apps/backup_mongo/restore/",
                "/api/apps/backup_mongo/restore",
            ),
            (
                "POST",
                "/api/apps/backup_mongo/restore/",
                "/api/apps/backup_mongo/restore",
            ),
            (
                "GET",
                "/api/apps/backup_mongo/restore/schema",
                "/api/apps/backup_mongo/restore",
            ),
            (
                "GET",
                "/api/apps/backup_mongo/restore/some-task",
                "/api/apps/backup_mongo/restore",
            ),
        ],
    )
    def test_scoped_restore_routes_not_shadowed_by_parent(
        self, method: str, path: str, expected_prefix: str
    ) -> None:
        """Assert each nested restore app's canonical routes win over its parent's.

        A restore child app mounts right after its parent, and the parent exposes a
        greedy ``/{task_name}`` route; this guards that a request to a canonical
        restore URL resolves to a route under the restore app's own prefix rather
        than being captured as a parent backup task.
        """
        scope = {"type": "http", "method": method, "path": path, "headers": []}
        matched = next(
            (
                route.path
                for route in sep_app.router.routes
                if route.matches(scope)[0] == Match.FULL
            ),
            None,
        )
        assert matched is not None
        assert matched.startswith(expected_prefix), f"{path} resolved to {matched}"
