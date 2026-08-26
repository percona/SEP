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

"""Define tests for the app.sep.main module."""

import importlib
import logging
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import URL

import app.sep.main as main_module
import app.sep.routes.artifacts as artifacts_module
from app.core.alerts.config import alert_settings, AlertSettings
from app.core.auth.exceptions import BaseAuthProviderException
from app.core.security import crypto_timestamp_serializer
from app.core.settings_override.lifecycle import ProxyEntry
from app.core.settings_override.models import SettingClassEnum
from app.sep.api.router import apps_router
from app.sep.apps.alerts.config import alerts_settings, AlertsSettings
from app.sep.apps.framework.base import BaseApp
from app.sep.apps.framework.registry import (
    AppRegistry,
    get_app_registry,
)
from app.sep.apps.report.config import health_report_settings, HealthReportSettings
from app.sep.artifact_constants import ARTIFACT_DOWNLOAD_SALT
from app.sep.config import App, sep_settings, SEPSettings
from app.sep.deps import get_session, PROTECTED_APP_KEYS
from app.sep.main import lifespan as sep_module_lifespan
from app.sep.main import (
    sep_app,
    sep_lifespan,
    warn_if_ambient_sso_inert,
    warn_if_external_base_lacks_prefix,
)
from app.sep.models import AppLifecycleEnum, AppState
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.constants import ARTIFACT_TYPE_SNIPPET
from tests.app.sep.conftest import REDUCED_ACTIVATION

_ORIGINAL_SEP_APP = main_module.sep_app

_BASE_URL_TARGET = "app.core.config.settings.BASE_URL"
_SNIPPETS_BASE_URL_TARGET = (
    "app.sep.snippets.config.snippets_settings.SNIPPETS_BASE_URL"
)


def _reload_restoring_identity() -> None:
    """Reload ``app.sep.main`` and put the original ``sep_app`` object back.

    ``importlib.reload`` re-executes the module in the same ``__dict__``,
    rebuilding ``sep_app`` as a new object while every consumer that did
    ``from app.sep.main import sep_app`` still holds the discarded one.
    Restoring the original binding keeps those consumers live; the rebuilt
    app is built over the real registry, so the two are interchangeable.
    """
    importlib.reload(main_module)
    main_module.sep_app = _ORIGINAL_SEP_APP


def _route_has_app_guard(route) -> bool:
    """Return whether a route carries the ``require_app_enabled`` guard.

    The router-level ``Depends(require_app_enabled(<key>))`` injected at mount
    time surfaces as a sub-dependency of the route's ``dependant`` whose
    callable is the closure ``require_app_enabled.<locals>._gate``.
    """
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    return any(
        getattr(sub.call, "__qualname__", "").endswith(
            "require_app_enabled.<locals>._gate"
        )
        for sub in dependant.dependencies
    )


def test_sep_app_lifespan_is_always_set():
    """Assert ``sep_lifespan`` is always assigned at module level.

    The lifespan must not be gated behind a ``__name__`` check, because uvicorn
    re-imports the module with ``__name__ == "app.sep.main"`` rather than
    ``"__main__"``, which would leave the lifespan as ``None``.
    """
    assert sep_module_lifespan is sep_lifespan


@pytest.fixture
def logger_mock(mocker) -> Mock:
    """Mock the logger for the app.sep.main module."""
    return mocker.patch("app.sep.main.logger")


@pytest.mark.asyncio
class TestBootSnippetIngestion:
    """Cover the ``SYNC_ON_STARTUP`` boot ingestion in ``sep_startup``.

    The sync task is library-owned and statically included, so boot ingestion is
    gated only on the setting -- never on the snippets app being activated. It is
    deliberately not re-homed as an app-owned startup hook, which would run only
    when the app ships.
    """

    async def test_enqueues_sync_with_the_snippets_app_deactivated(self, mocker):
        """Fire the sync at boot from an activation list without snippets."""
        mocker.patch.object(main_module, "init_sep_db", new_callable=AsyncMock)
        mocker.patch.object(snippets_settings, "SYNC_ON_STARTUP", new=True)
        mocker.patch.object(sep_settings, "APPS", [App(module_name="inventory")])
        delay = mocker.patch.object(main_module.sync_snippets, "delay")

        await main_module.sep_startup()

        delay.assert_called_once_with()

    async def test_does_not_enqueue_when_the_setting_is_off(self, mocker):
        """Leave the sync unqueued when ``SYNC_ON_STARTUP`` is disabled."""
        mocker.patch.object(main_module, "init_sep_db", new_callable=AsyncMock)
        mocker.patch.object(snippets_settings, "SYNC_ON_STARTUP", new=False)
        delay = mocker.patch.object(main_module.sync_snippets, "delay")

        await main_module.sep_startup()

        delay.assert_not_called()


class TestAmbientSsoStartupWarning:
    """Test the startup warning for an inert ambient-SSO toggle."""

    def test_warns_when_enabled_under_non_ambient_provider(self, mocker):
        """Emit a warning when the toggle is on but the active provider can't honor it."""
        mocker.patch.object(sep_settings, "AMBIENT_SESSION_SSO_ENABLED", new=True)
        warning = mocker.patch("app.sep.main.logger.warning")

        warn_if_ambient_sso_inert()

        warning.assert_called_once()

    def test_no_warning_when_provider_supports_ambient(self, mocker, grafana_mock):
        """Skip the warning when the active provider supports ambient sessions."""
        mocker.patch.object(sep_settings, "AMBIENT_SESSION_SSO_ENABLED", new=True)
        warning = mocker.patch("app.sep.main.logger.warning")

        warn_if_ambient_sso_inert()

        warning.assert_not_called()

    def test_no_warning_when_toggle_off(self, mocker):
        """Skip the warning when ambient SSO is disabled (default)."""
        warning = mocker.patch("app.sep.main.logger.warning")

        warn_if_ambient_sso_inert()

        warning.assert_not_called()


class TestExternalBaseStartupWarning:
    """Cover the startup advisory for an external base that omits the URL prefix."""

    @pytest.mark.parametrize(
        ("offending", "unset"),
        [
            (_BASE_URL_TARGET, _SNIPPETS_BASE_URL_TARGET),
            (_SNIPPETS_BASE_URL_TARGET, _BASE_URL_TARGET),
        ],
    )
    def test_warns_when_a_configured_base_omits_the_prefix(
        self, mocker, caplog, offending, unset
    ):
        """Warn once per offending base, naming the setting an operator must fix."""
        mocker.patch.object(sep_settings, "ROOT_PATH", new="/sep")
        mocker.patch(offending, new=URL("https://host"))
        mocker.patch(unset, new=None)

        with caplog.at_level(logging.WARNING):
            warn_if_external_base_lacks_prefix()

        assert len(caplog.records) == 1
        assert caplog.records[0].getMessage().startswith(offending.rsplit(".", 1)[1])

    def test_stays_silent_when_the_bases_carry_the_prefix(self, mocker, caplog):
        """Skip the warning when both bases already resolve under the prefix."""
        mocker.patch.object(sep_settings, "ROOT_PATH", new="/sep")
        mocker.patch(_BASE_URL_TARGET, new=URL("https://host/sep"))
        mocker.patch(_SNIPPETS_BASE_URL_TARGET, new=URL("https://host/sep"))

        with caplog.at_level(logging.WARNING):
            warn_if_external_base_lacks_prefix()

        assert caplog.records == []

    def test_stays_silent_when_no_external_base_is_configured(self, mocker, caplog):
        """Skip the warning when a prefix is set but neither external base is."""
        mocker.patch.object(sep_settings, "ROOT_PATH", new="/sep")
        mocker.patch(_BASE_URL_TARGET, new=None)
        mocker.patch(_SNIPPETS_BASE_URL_TARGET, new=None)

        with caplog.at_level(logging.WARNING):
            warn_if_external_base_lacks_prefix()

        assert caplog.records == []

    def test_stays_silent_when_no_prefix_is_configured(self, mocker, caplog):
        """Leave the unprefixed deployment unwarned, which is the regression contract."""
        mocker.patch.object(sep_settings, "ROOT_PATH", new="")
        mocker.patch(_BASE_URL_TARGET, new=URL("https://host"))
        mocker.patch(_SNIPPETS_BASE_URL_TARGET, new=URL("https://host"))

        with caplog.at_level(logging.WARNING):
            warn_if_external_base_lacks_prefix()

        assert caplog.records == []


class TestPrefixedRouting:
    """Cover routing when an ASGI server mounts ``sep_app`` under a URL prefix."""

    @pytest.mark.parametrize("root_path", ["", "/sep"])
    def test_health_answers_under_the_configured_prefix(self, root_path):
        """Resolve the liveness probe at the prefixed path PMM's nginx forwards."""
        client = TestClient(sep_app, root_path=root_path)

        assert client.get(f"{root_path}/health").status_code == status.HTTP_200_OK

    def test_health_still_answers_unprefixed_under_a_prefix(self):
        """Keep the container healthcheck working: it probes loopback unprefixed."""
        client = TestClient(sep_app, root_path="/sep")

        assert client.get("/health").status_code == status.HTTP_200_OK

    def test_a_prefix_like_path_is_not_mis_stripped(self):
        """Reject ``/september`` rather than mangling it into a ``/sep`` match."""
        client = TestClient(sep_app, root_path="/sep", raise_server_exceptions=False)

        assert client.get("/september").status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize("root_path", ["", "/sep"])
    @pytest.mark.usefixtures("guarded_client")
    @pytest.mark.asyncio
    async def test_a_json_api_route_resolves_under_the_prefix(self, root_path):
        """Resolve an app's JSON route identically with and without the prefix."""
        client = TestClient(sep_app, root_path=root_path, raise_server_exceptions=False)

        response = client.get(f"{root_path}/api/apps/inventory/")

        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_async_client_resolves_under_the_prefix(self):
        """Cover the ``ASGITransport`` path the async fixtures reach the app through."""
        transport = ASGITransport(app=sep_app, root_path="/sep")
        client = AsyncClient(transport=transport, base_url="http://test")

        response = await client.get("/sep/health")
        await client.aclose()

        assert response.status_code == status.HTTP_200_OK


def test_sep_app_rebuilds_without_alerts_and_dipper(mocker):
    """Rebuild ``sep_app`` against the PMM-embedded activation list.

    Proves the registry and mount composition survive an activation list that
    omits alerts and dipper. It does **not** prove import-cleanliness against a
    tree with those packages stripped -- the dev checkout can still import them.
    ``tests/app/sep/test_import_boundary.py`` is what enforces that.
    """
    original_apps = sep_settings.APPS
    mocker.patch.object(sep_settings, "APPS", REDUCED_ACTIVATION)
    get_app_registry.cache_clear()

    try:
        importlib.reload(main_module)

        keys = {app.key for app in get_app_registry()}
        assert "alerts" not in keys
        assert "dipper" not in keys
    finally:
        sep_settings.APPS = original_apps
        get_app_registry.cache_clear()
        _reload_restoring_identity()


def test_embedded_activation_list_serves_a_snippet_download(mocker, tmp_path):
    """Serve an ATW-dispatched snippet download with the snippets app deactivated.

    Both halves of the artifact surface are import-time decisions — the mount in
    ``main`` and ``_BASE_DIRS`` in the route module — so both are rebuilt against
    the embedded activation list before the request. A 404 here means the router
    was not mounted; a 400 means the snippet type did not resolve.
    """
    original_apps = sep_settings.APPS
    (tmp_path / "collect.sh").write_text("#!/bin/bash\necho hello")
    token = crypto_timestamp_serializer.dumps(
        {"type": ARTIFACT_TYPE_SNIPPET, "filename": "collect.sh", "md5": "abc123"},
        salt=ARTIFACT_DOWNLOAD_SALT,
    )

    mocker.patch.object(sep_settings, "APPS", REDUCED_ACTIVATION)
    get_app_registry.cache_clear()
    try:
        importlib.reload(artifacts_module)
        importlib.reload(main_module)

        with patch("app.sep.snippets.config.snippets_settings.SNIPPETS_DIR", tmp_path):
            client = TestClient(main_module.sep_app, raise_server_exceptions=False)
            response = client.get(f"/artifacts/download/{token}")

        assert response.status_code == status.HTTP_200_OK
    finally:
        sep_settings.APPS = original_apps
        get_app_registry.cache_clear()
        importlib.reload(artifacts_module)
        _reload_restoring_identity()


async def _refresher_proxy_map(mocker) -> dict[SettingClassEnum, ProxyEntry]:
    """Return the proxy map ``sep_overrides_lifespan`` hands to the refresher.

    :param mocker: The ``pytest-mock`` fixture used to stub the refresher.
    :return: The composed app-owned-plus-SEP proxy map.
    """
    captured: dict[SettingClassEnum, ProxyEntry] = {}

    @asynccontextmanager
    async def fake_refresher(_session_maker, proxies, *_args, **_kwargs):
        captured.update(proxies)
        yield

    mocker.patch.object(main_module, "settings_override_refresher", fake_refresher)
    original_callbacks = getattr(main_module.sep_app.state, "override_callbacks", None)
    try:
        async with main_module.sep_overrides_lifespan(FastAPI()):
            pass
    finally:
        main_module.sep_app.state.override_callbacks = original_callbacks
    return captured


@pytest.mark.asyncio
async def test_proxy_map_composes_app_owned_and_sep_entries(mocker):
    """Compose the refresher map from the app-owned seam plus SEP's own set."""
    proxies = await _refresher_proxy_map(mocker)

    assert set(proxies) == {
        SettingClassEnum.SEP_SETTINGS,
        SettingClassEnum.SNIPPETS_SETTINGS,
        SettingClassEnum.SETTINGS,
        SettingClassEnum.ALERT_SETTINGS,
        AlertsSettings.__name__,
        HealthReportSettings.__name__,
    }
    alerts_entry = proxies[AlertsSettings.__name__]
    assert alerts_entry.proxy is alerts_settings
    assert alerts_entry.settings_cls is AlertsSettings
    report_entry = proxies[HealthReportSettings.__name__]
    assert report_entry.proxy is health_report_settings
    assert report_entry.settings_cls is HealthReportSettings


@pytest.mark.asyncio
async def test_lifespan_refreshes_exactly_the_shared_builder_map(mocker):
    """Hand the refresher whatever ``build_sep_override_proxies`` composes.

    The Celery worker's SEP-side handler refreshes the same builder's output, so
    delegating here -- rather than composing an equivalent set inline -- is what
    keeps the two processes from drifting.
    """
    sentinel = {
        SettingClassEnum.SEP_SETTINGS: ProxyEntry(sep_settings, SEPSettings),
    }
    mocker.patch.object(
        main_module, "build_sep_override_proxies", return_value=sentinel
    )

    proxies = await _refresher_proxy_map(mocker)

    assert proxies == sentinel


@pytest.mark.asyncio
async def test_proxy_map_drops_alerts_but_keeps_core_alert_settings(mocker):
    """Drop ``AlertsSettings`` under reduced activation, keeping ``ALERT_SETTINGS``.

    ``ALERT_SETTINGS`` arrives from SEP's own set rather than the app-owned
    seam, so the PMM-embedded profile still refreshes the alert-delivery config
    that the Tasks worker and seven non-alerts apps read.
    """
    mocker.patch.object(sep_settings, "APPS", REDUCED_ACTIVATION)
    get_app_registry.cache_clear()
    try:
        proxies = await _refresher_proxy_map(mocker)
    finally:
        get_app_registry.cache_clear()

    assert AlertsSettings.__name__ not in proxies
    assert HealthReportSettings.__name__ not in proxies
    alert_entry = proxies[SettingClassEnum.ALERT_SETTINGS]
    assert alert_entry.proxy is alert_settings
    assert alert_entry.settings_cls is AlertSettings


@contextmanager
def _reloaded_against(mocker, registry):
    """Rebuild ``sep_app`` over ``registry``, restoring the real one on exit.

    Patches the registry accessor at its **source** module: ``importlib.reload``
    re-executes ``main``'s ``from ... import get_app_registry``, which would
    rebind over a patch applied to ``app.sep.main``.

    :param mocker: The ``pytest-mock`` fixture used to install the patch.
    :param registry: The registry ``app.sep.main`` should be rebuilt over.
    :return: The ``sep_app`` built from ``registry``.
    """
    mocker.patch(
        "app.sep.apps.framework.registry.get_app_registry", return_value=registry
    )
    try:
        importlib.reload(main_module)
        yield main_module.sep_app
    finally:
        mocker.stopall()
        get_app_registry.cache_clear()
        _reload_restoring_identity()


def test_sep_app_keeps_default_docs_urls():
    """``sep_app`` keeps FastAPI's default ``/docs`` and ``/redoc`` URLs.

    Only the top-level combined app disables the auto-generated docs.
    ``sep_app`` itself must retain default behavior so it stays self-describing in
    standalone use; the top-level ``_disabled_top_level_docs`` handler in
    ``app/main.py`` (registered before ``app.mount("/", sep_app)``) is what makes
    ``GET /docs`` on the combined app return 404 via mount-order precedence.
    """
    assert sep_app.docs_url == "/docs"
    assert sep_app.redoc_url == "/redoc"


@pytest.fixture
def guarded_client(test_client: TestClient, session) -> TestClient:
    """Build an authenticated client whose routes read the in-memory ``session``."""
    sep_app.dependency_overrides[get_session] = lambda: session
    yield test_client
    sep_app.dependency_overrides = {}


class TestAppStateGuards:
    """Integration tests for the per-app enable/disable route guards."""

    @pytest.mark.parametrize(
        ("plugin_key", "plugin_route"),
        [
            ("snippets", "/api/apps/snippets/"),
            ("checksums", "/api/apps/checksums/"),
        ],
    )
    @pytest.mark.parametrize(
        "state",
        [
            AppLifecycleEnum.DISABLED,
            AppLifecycleEnum.DISABLING,
            AppLifecycleEnum.ENABLING,
        ],
    )
    @pytest.mark.asyncio
    async def test_route_guard_returns_503_for_non_enabled_states(
        self, guarded_client: TestClient, session, plugin_key, plugin_route, state
    ) -> None:
        """Return 503 from a non-protected plugin's route whenever it is not ``ENABLED``."""
        session.add(AppState(app_key=plugin_key, lifecycle_state=state))
        await session.commit()

        response = guarded_client.get(plugin_route)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert plugin_key in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_child_route_503s_when_parent_disabled(
        self, guarded_client: TestClient, session
    ) -> None:
        """Return 503 from a child app's route when its parent is disabled (gate uses parent_key)."""
        session.add(
            AppState(app_key="backup_mongo", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await session.commit()

        response = guarded_client.get("/api/apps/backup_mongo/restore/")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "backup_mongo" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_inventory_route_never_503s(
        self, guarded_client: TestClient, session
    ) -> None:
        """Leave inventory ungated: it is protected, so a disabled row never gates it."""
        session.add(
            AppState(app_key="inventory", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await session.commit()

        response = guarded_client.get("/api/apps/inventory/")

        assert response.status_code != status.HTTP_503_SERVICE_UNAVAILABLE

    @pytest.mark.parametrize(
        "route",
        [
            "/api/apps/atw/",
            "/api/apps/alert_troubleshooting/",
        ],
    )
    @pytest.mark.asyncio
    async def test_snippet_consumer_routes_survive_a_snippets_disable(
        self, guarded_client: TestClient, session, route: str
    ) -> None:
        """Keep ATW and Alert Troubleshooting routes reachable past a snippets disable.

        Both read snippet scripts from the library rather than the snippets app,
        so neither declares ``requires_apps`` and the gate has nothing to trip on.
        """
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await session.commit()

        response = guarded_client.get(route)

        assert response.status_code != status.HTTP_503_SERVICE_UNAVAILABLE

    @pytest.mark.parametrize(
        "route",
        [
            "/api/apps/atw/",
            "/api/apps/alert_troubleshooting/",
        ],
    )
    @pytest.mark.asyncio
    async def test_snippet_consumer_routes_reachable_by_default(
        self, guarded_client: TestClient, route: str
    ) -> None:
        """Keep ATW and Alert Troubleshooting routes reachable with no state rows."""
        response = guarded_client.get(route)

        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_dependency_disabled_route_503s_naming_its_own_key(
        self, guarded_client: TestClient, session, mocker
    ) -> None:
        """Return 503 naming the gated app, not the dependency that is off.

        No shipped app declares ``requires_apps`` any more, so the guard's
        dependency arm is exercised against a synthetic registry: the route stays
        the real mounted one (the gate closure-captured ``atw`` at mount time)
        while the graph it resolves through is injected.
        """
        registry = AppRegistry(
            [
                BaseApp(
                    key="atw",
                    name="atw",
                    display_name="ATW",
                    uri_path="/atw",
                    requires_apps=("provider",),
                ),
                BaseApp(
                    key="provider",
                    name="provider",
                    display_name="Provider",
                    uri_path="/provider",
                ),
            ]
        )
        mocker.patch(
            "app.sep.apps.framework.registry.get_app_registry", return_value=registry
        )
        session.add(
            AppState(app_key="provider", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await session.commit()

        response = guarded_client.get("/api/apps/atw/")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["detail"] == "App 'atw' is currently disabled."

    def test_inventory_api_routes_are_not_guarded(self) -> None:
        """Carry no app-state guard on the protected ``inventory`` plugin's routes."""
        inventory_app = get_app_registry().get("inventory")
        assert inventory_app is not None
        inventory_prefix = inventory_app.uri_path
        for route in sep_app.routes:
            path = getattr(route, "path", "")
            if path == inventory_prefix or path.startswith(f"{inventory_prefix}/"):
                assert not _route_has_app_guard(route)

    def test_json_api_mount_loop_guards_non_protected_plugins(self) -> None:
        """Every non-protected JSON-API plugin sub-router carries the guard."""
        guarded_keys = {
            key
            for p in sep_settings.APPS
            if (key := p.module_name.split(".")[-1]) not in PROTECTED_APP_KEYS
            and p.api_router_path
        }
        seen = set()
        for route in apps_router.routes:
            path = getattr(route, "path", "")
            for key in guarded_keys:
                if (
                    path.startswith(f"/apps/{key}/") or path == f"/apps/{key}"
                ) and _route_has_app_guard(route):
                    seen.add(key)
        assert guarded_keys <= seen


class TestJsonExceptionHandlers:
    """Cover the exception handlers now that every branch returns JSON.

    The handlers used to pick between a JSON body and a 303-redirect-with-flash
    based on the request path; with the server-rendered UI gone, there is no
    non-JSON branch left, so a non-``/api`` path must get the same JSON shape as
    an ``/api`` one.
    """

    @staticmethod
    def _raising_route(exc: Exception) -> TestClient:
        """Return a client for a throwaway app that raises ``exc`` at ``/boom``."""
        app = FastAPI(exception_handlers=sep_app.exception_handlers)

        @app.get("/boom")
        async def _boom() -> None:
            raise exc

        return TestClient(app, raise_server_exceptions=False)

    def test_404_on_non_api_path_returns_json(self, test_client: TestClient) -> None:
        """Return a JSON 404 body, never a redirect, for an unmatched non-API path."""
        response = test_client.get("/no-such-path", follow_redirects=False)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"detail": "Not Found"}

    def test_deleted_shell_routes_are_gone(self, test_client: TestClient) -> None:
        """Assert the login/logout/homepage shell routes 404 after the SSR removal."""
        for method, path in (
            ("get", "/login"),
            ("post", "/login"),
            ("post", "/logout"),
            ("get", "/"),
        ):
            response = getattr(test_client, method)(path, follow_redirects=False)
            assert response.status_code == status.HTTP_404_NOT_FOUND, path

    def test_http_exception_with_headers_returns_json(self) -> None:
        """Forward ``headers`` on the JSON body instead of redirecting to the referer."""
        client = self._raising_route(
            HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="nope",
                headers={"x-sep-test": "1"},
            )
        )

        response = client.get("/boom", headers={"referer": "/somewhere"})

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json() == {"detail": "nope"}
        assert response.headers["x-sep-test"] == "1"

    def test_auth_provider_exception_returns_json(self) -> None:
        """Return the provider failure as JSON rather than a 303 to the login page.

        The handler used to build its ``Location`` with ``url_for("login")``,
        which would now raise ``NoMatchFound`` — a 502-class upstream failure
        would surface as an unhandled 500.
        """
        client = self._raising_route(BaseAuthProviderException())

        response = client.get("/boom", follow_redirects=False)

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json() == {
            "detail": "Error getting response from auth provider."
        }

    def test_request_validation_error_returns_json(self) -> None:
        """Return the encoded validator failures, not a flash-and-redirect."""
        app = FastAPI(exception_handlers=sep_app.exception_handlers)

        @app.post("/validate")
        async def _validate(payload: dict[str, int]) -> None:
            """Reject a malformed body through FastAPI's own validation."""

        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/validate", json={"n": "not-an-int"}, headers={"referer": "/form"}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = response.json()["detail"]
        assert isinstance(detail, list)
        assert {"loc", "msg"} <= set(detail[0])
