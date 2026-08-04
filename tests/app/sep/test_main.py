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
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from starlette.routing import Mount

import app.sep.main as main_module
from app.core.alerts.config import alert_settings, AlertSettings
from app.core.auth.exceptions import (
    BaseAuthProviderException,
    HTTPForbiddenException,
    HTTPUnauthorizedException,
)
from app.core.exceptions import HTTPBadGatewayException, HTTPServiceUnavailableException
from app.core.settings_override.lifecycle import ProxyEntry
from app.core.settings_override.models import SettingClassEnum
from app.sep.api.router import apps_router
from app.sep.apps.alerts.config import alerts_settings, AlertsSettings
from app.sep.apps.dipper.constants import DIPPER_PAYLOADS_DIR
from app.sep.apps.framework.base import BaseApp
from app.sep.apps.framework.registry import (
    AppRegistry,
    build_app_registry,
    get_app_registry,
)
from app.sep.config import App, sep_settings, SEPSettings
from app.sep.deps import get_access_token_from_cookie, get_session, PROTECTED_APP_KEYS
from app.sep.exceptions import LoginRedirectException
from app.sep.main import (
    _safe_next_path,
    get_tasks_index_context,
    sep_app,
    sep_lifespan,
    templates,
    warn_if_ambient_sso_inert,
)
from app.sep.main import lifespan as sep_module_lifespan
from app.sep.models import AppLifecycleEnum, AppState
from app.sep.snippets.config import snippets_settings
from tests.app.factories import OAuthTokenFactory
from tests.app.sep.conftest import REDUCED_ACTIVATION

_ORIGINAL_SEP_APP = main_module.sep_app


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
def test_client_with_session_cookie(test_client: TestClient) -> TestClient:
    """Create an authenticated test client for the app with the session cookie set."""
    test_client.cookies[sep_settings.SESSION.COOKIE_NAME] = "existing_session"
    return test_client


@pytest.fixture
def logger_mock(mocker) -> Mock:
    """Mock the logger for the app.sep.main module."""
    return mocker.patch("app.sep.main.logger")


@pytest.fixture
def dummy_context() -> dict[str, str]:
    """Override get_tasks_index_context and return dummy dict context."""
    ctx = {"message": "Welcome Home"}
    sep_app.dependency_overrides[get_tasks_index_context] = lambda: ctx
    yield ctx
    sep_app.dependency_overrides = {}


@pytest.fixture
def dummy_access_token() -> str:
    """Override get_access_token_from_cookie and return dummy access token."""
    fake_access_token = "access-token"
    sep_app.dependency_overrides[get_access_token_from_cookie] = lambda: (
        fake_access_token
    )
    yield fake_access_token
    sep_app.dependency_overrides = {}


class TestSafeNextPath:
    """Define test suite for the ``_safe_next_path`` open-redirect guard."""

    @pytest.mark.parametrize(
        ("next_path", "expected"),
        [
            ("/", "/"),
            ("/apps/inventory", "/apps/inventory"),
            ("/settings?tab=1", "/settings?tab=1"),
            ("http://evil.com/x", "/"),
            ("https://evil.com/x", "/"),
            ("//evil.com", "/"),
            ("//evil.com/path", "/"),
            ("/\\evil.com", "/"),
            ("relative/path", "/"),
            ("", "/"),
        ],
    )
    def test_collapses_unsafe_targets(self, next_path, expected):
        """Pass through same-origin paths; collapse scheme/protocol-relative targets to ``/``."""
        assert _safe_next_path(next_path) == expected


class TestLogin:
    """Define test suite for GET and POST login routes."""

    def test_login_form_renders_template(self, mocker, test_client):
        """Test the GET /login route.

        When an unauthenticated user GETs /login (no session cookie),
        the login form route should call TemplateResponse with the correct
        template name and context.
        """
        dummy_html = "<html>Login Form</html>"
        dummy_response = HTMLResponse(content=dummy_html)
        template_patch = mocker.patch(
            "app.sep.main.templates.TemplateResponse", return_value=dummy_response
        )

        response = test_client.get("/login")

        assert response.status_code == status.HTTP_200_OK
        template_patch.assert_called_once()
        _, kwargs = template_patch.call_args
        assert kwargs.get("name") == "login.html.j2"
        context = kwargs.get("context", {})
        assert "csrf_token" in context

    def test_get_login_redirects_if_authenticated(
        self, test_client_with_session_cookie
    ):
        """Test the GET /login route for an already authenticated user.

        If a user is already authenticated (i.e. has the session cookie)
        then GET /login should raise a redirect.
        """
        response = test_client_with_session_cookie.get("/login", follow_redirects=False)

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"

    @pytest.mark.parametrize(
        ("next_path", "expected_location"),
        [
            (None, "/"),
            ("", "/"),
            ("/", "/"),
            ("/fake-page", "/fake-page"),
            ("http://127.0.0.1/fake-page", "/"),
            ("//evil.com", "/"),
            ("/\\evil.com", "/"),
        ],
    )
    def test_post_login_success(
        self, mocker, test_client, next_path, expected_location
    ):
        """Test the POST /login route.

        A successful POST /login should (a) call the User.get_oauth_token
        to verify credentials, (b) serialize the access token, (c) set a cookie,
        and (d) return a redirect response.
        """
        username = "testuser"
        fake_access_token = "fake_access_token"
        get_oauth_token_patch = mocker.patch(
            "app.sep.main.User.get_oauth_token",
            new_callable=mocker.AsyncMock,
            return_value=OAuthTokenFactory.build(access_token=fake_access_token),
        )
        invalidate_tokens_for_user_patch = mocker.patch(
            "app.sep.main.User.invalidate_tokens_for_user",
            new_callable=mocker.AsyncMock,
        )
        dumps_patch = mocker.patch(
            "app.sep.main.crypto_timestamp_serializer.dumps",
            return_value="serialized_fake_token",
        )
        form_data = {"username": username, "password": "secret"}

        login_route = "/login"
        if next_path is not None:
            login_route += f"?next={next_path}"
        response = test_client.post(login_route, data=form_data, follow_redirects=False)

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == expected_location
        cookie_header = response.headers.get("set-cookie", "")
        assert sep_settings.SESSION.COOKIE_NAME in cookie_header
        assert "serialized_fake_token" in cookie_header
        get_oauth_token_patch.assert_awaited_once_with(
            username=username, password="secret"
        )
        invalidate_tokens_for_user_patch.assert_awaited_once_with(
            username, exclude_tokens=[fake_access_token]
        )
        dumps_patch.assert_called_once_with(fake_access_token)

    def test_post_login_redirects_if_authenticated(
        self, test_client_with_session_cookie
    ):
        """Test the POST /login route for an already authenticated user.

        If the client sends a session cookie, the POST /login route
        should not try to reauthenticate but instead immediately redirect.
        """
        form_data = {"username": "testuser", "password": "secret"}

        response = test_client_with_session_cookie.post(
            "/login", data=form_data, follow_redirects=False
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"

    def test_get_login_auto_logs_in_from_ambient_session(
        self, mocker, test_client, grafana_mock
    ):
        """Authenticate on GET /login from a valid ambient Grafana session, skipping the form."""
        mocker.patch.object(sep_settings, "AMBIENT_SESSION_SSO_ENABLED", new=True)
        dumps_patch = mocker.patch(
            "app.sep.main.crypto_timestamp_serializer.dumps",
            return_value="serialized_ambient_token",
        )

        response = test_client.get(
            "/login?next=/fake-page",
            cookies={"grafana_session": "ambient"},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/fake-page"
        cookie_header = response.headers.get("set-cookie", "")
        assert sep_settings.SESSION.COOKIE_NAME in cookie_header
        assert "serialized_ambient_token" in cookie_header
        assert dumps_patch.called

    def test_get_login_auto_login_sanitizes_external_next(
        self, mocker, test_client, grafana_mock
    ):
        """Collapse an external ``next`` to ``/`` during ambient auto-login (open-redirect guard)."""
        mocker.patch.object(sep_settings, "AMBIENT_SESSION_SSO_ENABLED", new=True)
        mocker.patch(
            "app.sep.main.crypto_timestamp_serializer.dumps", return_value="tok"
        )

        response = test_client.get(
            "/login?next=http://127.0.0.1/evil",
            cookies={"grafana_session": "ambient"},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"

    def test_get_login_falls_back_to_form_on_rejected_session(
        self, mocker, test_client, grafana_mock
    ):
        """Render the login form silently when Grafana rejects the ambient session."""
        mocker.patch.object(sep_settings, "AMBIENT_SESSION_SSO_ENABLED", new=True)
        grafana_mock.get_current_user.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED
        )
        template_patch = mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            return_value=HTMLResponse("<html>form</html>"),
        )

        response = test_client.get(
            "/login", cookies={"grafana_session": "stale"}, follow_redirects=False
        )

        assert response.status_code == status.HTTP_200_OK
        template_patch.assert_called_once()

    def test_get_login_renders_form_when_toggle_off(
        self, mocker, test_client, grafana_mock
    ):
        """Render the form on GET /login when ambient SSO is disabled, despite a cookie."""
        template_patch = mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            return_value=HTMLResponse("<html>form</html>"),
        )

        response = test_client.get(
            "/login", cookies={"grafana_session": "ambient"}, follow_redirects=False
        )

        assert response.status_code == status.HTTP_200_OK
        template_patch.assert_called_once()


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


class TestLogout:
    """Define test suite for logout route."""

    def test_logout_success(
        self, mocker, dummy_access_token, test_client_with_session_cookie
    ):
        """Test a successful logout request.

        A successful POST /logout should delete the session cookie,
        attempt to invalidate the OAuth token and return a redirect.
        """
        invalidate_patch = mocker.patch(
            "app.sep.main.User.invalidate_oauth_token",
            new_callable=mocker.AsyncMock,
        )

        response = test_client_with_session_cookie.post(
            "/logout", follow_redirects=False
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"
        cookie_header = response.headers.get("set-cookie", "")
        assert sep_settings.SESSION.COOKIE_NAME in cookie_header
        invalidate_patch.assert_awaited_once_with(dummy_access_token)

    def test_logout_handles_invalidation_error(
        self, mocker, dummy_access_token, test_client_with_session_cookie
    ):
        """Test that logout route always redirects.

        Even if User.invalidate_oauth_token raises an error (e.g. KeyError)
        the logout route should still return a redirect response.
        """
        mocker.patch(
            "app.sep.main.User.invalidate_oauth_token",
            new_callable=mocker.AsyncMock,
            side_effect=KeyError("invalid token"),
        )

        response = test_client_with_session_cookie.post(
            "/logout",
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"
        cookie_header = response.headers.get("set-cookie", "")
        assert sep_settings.SESSION.COOKIE_NAME in cookie_header


def test_read_root_renders_homepage(mocker, dummy_context, test_client):
    """Test that the index page properly renders the homepage template.

    GET / (the homepage) should render the homepage template with the context
    provided by get_tasks_index_context.
    """
    dummy_html = "<html>Homepage</html>"
    template_patch = mocker.patch(
        "app.sep.main.templates.TemplateResponse",
        return_value=HTMLResponse(content=dummy_html),
    )

    response = test_client.get("/")

    assert response.status_code == status.HTTP_200_OK
    template_patch.assert_called_once()
    _, kwargs = template_patch.call_args
    assert kwargs.get("name") == "homepage.html.j2"
    assert kwargs.get("context") == dummy_context


def test_task_routers_mounted_when_only_backup_pg_enabled(mocker):
    """Regression: task-infrastructure routers must be mounted for backup_pg-only installs.

    When backup_pg is the only task-related plugin enabled, the shared routers
    (periodic_tasks, stop_task, stream_logs, download_files, execution_events,
    inventory_ajax) must still be mounted so that Jinja url_for() calls like
    url_for('periodic_task_create') and url_for('stop_task_execution') resolve
    without raising NoMatchFound.
    """
    original_plugins = sep_settings.APPS
    mocker.patch.object(sep_settings, "APPS", [App(module_name="backup_pg")])
    get_app_registry.cache_clear()

    try:
        importlib.reload(main_module)

        route_names = {r.name for r in main_module.sep_app.routes}
        assert "periodic_task_create" in route_names
        assert "stop_task_execution" in route_names
    finally:
        sep_settings.APPS = original_plugins
        get_app_registry.cache_clear()
        _reload_restoring_identity()


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
        SettingClassEnum.MESSAGES_SETTINGS,
        SettingClassEnum.SETTINGS,
        SettingClassEnum.ALERT_SETTINGS,
        SettingClassEnum.ALERTS_SETTINGS,
    }
    alerts_entry = proxies[SettingClassEnum.ALERTS_SETTINGS]
    assert alerts_entry.proxy is alerts_settings
    assert alerts_entry.settings_cls is AlertsSettings


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
    """Drop ``ALERTS_SETTINGS`` under reduced activation, keeping ``ALERT_SETTINGS``.

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

    assert SettingClassEnum.ALERTS_SETTINGS not in proxies
    alert_entry = proxies[SettingClassEnum.ALERT_SETTINGS]
    assert alert_entry.proxy is alert_settings
    assert alert_entry.settings_cls is AlertSettings


def test_periodic_router_mounted_when_only_inventory_enabled(mocker):
    """Regression: ``/periodic`` routes must be mounted for inventory-only installs.

    The inventory plugin's node-list page renders ``url_for('periodic_task_create')``
    unconditionally as part of the inline schedule UI, so the periodic-tasks router
    must be mounted whenever the inventory plugin is enabled even if no task-oriented
    plugin (tasks, backup, checksums, …) is configured.
    """
    original_plugins = sep_settings.APPS
    mocker.patch.object(sep_settings, "APPS", [App(module_name="inventory")])
    get_app_registry.cache_clear()

    try:
        importlib.reload(main_module)

        route_names = {r.name for r in main_module.sep_app.routes}
        assert "periodic_task_create" in route_names
        assert "periodic_task_update" in route_names
        assert "periodic_task_delete" in route_names
    finally:
        sep_settings.APPS = original_plugins
        get_app_registry.cache_clear()
        _reload_restoring_identity()


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


@pytest.fixture
def jinja_free_registry() -> AppRegistry:
    """Return the real registry with every ``jinja_router`` stripped."""
    get_app_registry.cache_clear()
    return AppRegistry(
        [
            app.model_copy(update={"jinja_router": None})
            for app in build_app_registry(sep_settings.APPS)
        ]
    )


def test_reload_helpers_restore_sep_app_identity(mocker, jinja_free_registry):
    """Verify reload-based helpers leave ``sep_app``'s identity intact.

    Consumers across ~53 modules bind ``sep_app`` by value at import. A reload
    that leaves a rebuilt object in the module dict silently strands them.
    """
    assert main_module.sep_app is sep_app

    with _reloaded_against(mocker, jinja_free_registry) as rebuilt:
        assert rebuilt is not sep_app

    assert main_module.sep_app is sep_app


class TestJinjaDecoupledMounts:
    """Cover the shared data surface's independence from Jinja-router mounting."""

    def test_task_data_surface_survives_zero_jinja_routers(
        self, mocker, jinja_free_registry: AppRegistry
    ) -> None:
        """Mount the shared task-data routes and payload dirs with no Jinja UI at all."""
        with _reloaded_against(mocker, jinja_free_registry) as app:
            route_names = {route.name for route in app.routes}
            assert "list_task_history_files" in route_names
            assert "task_logs_event_stream" in route_names
            assert "list_task_execution_events" in route_names

            mounts = {
                route.path: route.name
                for route in app.routes
                if isinstance(route, Mount)
            }
            assert mounts["/static/snippets"] == "snippets_files"
            assert mounts["/static/dipper"] == "dipper_files"

            assert "periodic_task_create" not in route_names
            assert "stop_task_execution" not in route_names

    def test_payload_mounts_precede_catch_all_static(
        self, mocker, jinja_free_registry: AppRegistry
    ) -> None:
        """Register both payload mounts ahead of the catch-all ``/static`` mount."""
        with _reloaded_against(mocker, jinja_free_registry) as app:
            paths = [route.path for route in app.routes if isinstance(route, Mount)]

            assert paths.index("/static/snippets") < paths.index("/static")
            assert paths.index("/static/dipper") < paths.index("/static")

    def test_task_data_routers_absent_without_a_declaring_app(self, mocker) -> None:
        """Withhold the shared task-data routes when no app declares it needs them."""
        registry = AppRegistry(
            [
                BaseApp(
                    key="legacy",
                    name="Legacy",
                    uri_path="/legacy",
                    jinja_router=APIRouter(),
                )
            ]
        )

        with _reloaded_against(mocker, registry) as app:
            route_names = {route.name for route in app.routes}
            assert "list_task_history_files" not in route_names
            assert "task_logs_event_stream" not in route_names
            assert "list_task_execution_events" not in route_names

            assert "periodic_task_create" in route_names
            assert "stop_task_execution" in route_names

    def test_empty_registry_mounts_neither_surface(self, mocker) -> None:
        """Mount no shared routers and no payload dirs when no app is activated."""
        with _reloaded_against(mocker, AppRegistry([])) as app:
            route_names = {route.name for route in app.routes}
            assert "list_task_history_files" not in route_names
            assert "periodic_task_create" not in route_names

            mounts = {route.path for route in app.routes if isinstance(route, Mount)}
            assert "/static/snippets" not in mounts
            assert "/static/dipper" not in mounts
            assert "/static" in mounts

    def test_child_apps_inherit_uses_task_data(self) -> None:
        """Cover a child app inheriting the opt-in with no declaration of its own."""
        get_app_registry.cache_clear()
        registry = build_app_registry(sep_settings.APPS)

        assert registry.get("mysql_backups/restore").uses_task_data is True


class TestPayloadStaticMounts:
    """Cover the authenticated payload mounts end-to-end over real HTTP."""

    def test_snippets_payload_mount_serves_authenticated(
        self, mocker, test_client: TestClient
    ) -> None:
        """Serve a snippets payload file to an authenticated caller."""
        mocker.patch("app.sep.utils.static.get_current_user", new=AsyncMock())
        filename = next(p.name for p in snippets_settings.SNIPPETS_DIR.glob("*.sh"))

        response = test_client.get(f"/static/snippets/{filename}")

        assert response.status_code == status.HTTP_200_OK

    def test_snippets_payload_mount_rejects_anonymous(
        self, test_client: TestClient
    ) -> None:
        """Refuse an anonymous request for a snippets payload file."""
        filename = next(p.name for p in snippets_settings.SNIPPETS_DIR.glob("*.sh"))

        response = test_client.get(
            f"/static/snippets/{filename}", follow_redirects=False
        )

        assert response.status_code != status.HTTP_200_OK

    def test_dipper_payload_mount_serves_authenticated(
        self, mocker, test_client: TestClient
    ) -> None:
        """Serve a dipper payload file to an authenticated caller."""
        mocker.patch("app.sep.utils.static.get_current_user", new=AsyncMock())
        filename = next(p.name for p in DIPPER_PAYLOADS_DIR.glob("*.sh"))

        response = test_client.get(f"/static/dipper/{filename}")

        assert response.status_code == status.HTTP_200_OK

    def test_dipper_payload_mount_rejects_anonymous(
        self, test_client: TestClient
    ) -> None:
        """Refuse an anonymous request for a dipper payload file."""
        filename = next(p.name for p in DIPPER_PAYLOADS_DIR.glob("*.sh"))

        response = test_client.get(f"/static/dipper/{filename}", follow_redirects=False)

        assert response.status_code != status.HTTP_200_OK


class TestExceptionHandlers:
    """Define test suite for exception handlers."""

    def test_default_error_handler(self, mocker, dummy_context, test_client):
        """Test that HTTPExceptions are caught and properly handled."""
        error_detail = "Internal Server Error"
        fake_referer = "/fake-page"
        mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_detail
            ),
        )
        messages_error_mock = mocker.patch("app.sep.main.messages.error")

        response = test_client.get(
            "/", headers={"Referer": fake_referer}, follow_redirects=False
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == fake_referer
        messages_error_mock.assert_called_once_with(mocker.ANY, error_detail)

    @pytest.mark.parametrize(
        ("exc", "expected_status"),
        [
            pytest.param(
                HTTPBadGatewayException("PMM is unreachable"),
                status.HTTP_502_BAD_GATEWAY,
                id="bad_gateway",
            ),
            pytest.param(
                HTTPServiceUnavailableException("PMM is unavailable"),
                status.HTTP_503_SERVICE_UNAVAILABLE,
                id="service_unavailable",
            ),
        ],
    )
    def test_gateway_error_handler_returns_json_on_browser_path(
        self, mocker, dummy_context, test_client, exc, expected_status
    ):
        """Answer a gateway error with JSON even on a browser/session path.

        ``json_exception_handler`` is registered for the gateway exceptions, so a
        502/503 answers in JSON regardless of path or auth mode -- it does not fall
        through to ``default_exception_handler``'s flash-and-redirect. This pins the
        behaviour after the upstream-error mapping was widened so a header-bearing
        gateway error resolves to its mapped class instead of a bare HTTPException.
        """
        mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=exc,
        )
        messages_error_mock = mocker.patch("app.sep.main.messages.error")

        response = test_client.get(
            "/", headers={"Referer": "/fake-page"}, follow_redirects=False
        )

        assert response.status_code == expected_status
        assert response.json()["detail"] == exc.detail
        messages_error_mock.assert_not_called()

    @pytest.mark.parametrize(
        ("exc", "expected_status"),
        [
            pytest.param(
                HTTPUnauthorizedException(),
                status.HTTP_401_UNAUTHORIZED,
                id="bearer_unauthorized",
            ),
            pytest.param(
                HTTPForbiddenException("User is not active"),
                status.HTTP_403_FORBIDDEN,
                id="bearer_forbidden",
            ),
        ],
    )
    def test_default_error_handler_bearer_returns_json(
        self, mocker, dummy_context, test_client, exc, expected_status
    ):
        """Test returning JSON for Bearer-authenticated HTTP exceptions."""
        mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=exc,
        )

        response = test_client.get(
            "/",
            headers={"Authorization": "Bearer any-token"},
            follow_redirects=False,
        )

        assert response.status_code == expected_status
        assert response.json()["detail"] == exc.detail

    def test_default_error_handler_unauthorized_without_bearer_redirects(
        self, mocker, dummy_context, test_client
    ):
        """Test using referer redirect when Authorization Bearer is absent."""
        mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=HTTPUnauthorizedException(),
        )
        messages_error_mock = mocker.patch("app.sep.main.messages.error")
        fake_referer = "/some-page"

        response = test_client.get(
            "/",
            headers={"Referer": fake_referer},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == fake_referer
        messages_error_mock.assert_called_once()

    def test_auth_provider_exception_handler(
        self, mocker, dummy_access_token, dummy_context, test_client_with_session_cookie
    ):
        """Test that BaseAuthProviderException are caught and properly handled."""
        error_detail = "Error getting response from auth provider."
        mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=BaseAuthProviderException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=error_detail
            ),
        )
        messages_error_mock = mocker.patch("app.sep.main.messages.error")

        response = test_client_with_session_cookie.get(
            "/",
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/login?next=/"
        cookie_header = response.headers.get("set-cookie", "")
        assert sep_settings.SESSION.COOKIE_NAME in cookie_header
        messages_error_mock.assert_called_once_with(
            mocker.ANY, error_detail, sticky=True
        )

    def test_internal_error_handler(
        self,
        mocker,
        dummy_context,
        dummy_access_token,
        regular_user,
        logger_mock,
        test_client,
    ):
        """Test that unexpected 500 errors are caught and properly handled."""
        error_msg = "Unexpected error"
        unexpected_exc = ValueError(error_msg)
        base_uri = "http://127.0.0.1"
        formatted_exception = f"Line 1\nLine 2\n{error_msg}"
        get_base_url_patch = mocker.patch(
            "app.sep.main.get_base_url", return_value=base_uri
        )
        get_current_user_patch = mocker.patch(
            "app.sep.main.get_current_user", return_value=regular_user
        )
        get_default_context_patch = mocker.patch(
            "app.sep.main.get_default_context", return_value=dummy_context
        )
        template_patch = mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=[unexpected_exc, HTMLResponse(content="<html>Error</html>")],
        )
        messages_error_mock = mocker.patch("app.sep.main.messages.error")
        format_exception_patch = mocker.patch(
            "app.sep.main.format_exception",
            return_value=formatted_exception.splitlines(keepends=True),
        )

        test_client.get("/")

        get_base_url_patch.assert_called_once()
        logger_mock.exception.assert_called_once_with(
            "Unhandled exception:", exc_info=unexpected_exc
        )
        get_current_user_patch.assert_called_once()
        messages_error_mock.assert_called_once_with(
            mocker.ANY,
            "Internal Server Error. Please contact the administrators for help.",
            sticky=True,
        )
        format_exception_patch.assert_called_once_with(
            unexpected_exc, limit=-1, chain=False
        )
        get_default_context_patch.assert_called_once_with(
            mocker.ANY, regular_user, base_uri, mocker.ANY
        )
        template_patch.assert_called_with(
            request=mocker.ANY,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            name="error.html.j2",
            context={"exception": formatted_exception, **dummy_context},
        )

    def test_internal_error_handler_redirects_for_stale_session(
        self,
        mocker,
        dummy_context,
        logger_mock,
        test_client,
    ):
        """Test stale-session 500 handling redirects to login."""
        unexpected_exc = ValueError("Unexpected error")
        redirect_exc = LoginRedirectException(
            Request(
                {
                    "type": "http",
                    "scheme": "http",
                    "method": "GET",
                    "path": "/",
                    "raw_path": b"/",
                    "query_string": b"",
                    "headers": [],
                    "server": ("testserver", 80),
                    "client": ("testclient", 50000),
                    "root_path": "",
                    "app": sep_app,
                }
            )
        )
        mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=unexpected_exc,
        )
        mocker.patch("app.sep.main.get_current_user", side_effect=redirect_exc)
        messages_error_mock = mocker.patch("app.sep.main.messages.error")

        response = test_client.get("/", follow_redirects=False)

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/login?next=/"
        assert f'{sep_settings.SESSION.COOKIE_NAME}=""' in response.headers.get(
            "set-cookie", ""
        )
        logger_mock.exception.assert_called_once_with(
            "Unhandled exception:", exc_info=unexpected_exc
        )
        messages_error_mock.assert_not_called()

    @pytest.mark.usefixtures("mock_get_username_mapping")
    def test_404_error(self, mocker, regular_user, test_client):
        """Test 404 errors renders the 404 template for authenticated users."""
        mocker.patch("app.sep.main.get_current_user", return_value=regular_user)
        mocker.patch("app.sep.main.get_default_context", return_value={})
        template_spy = mocker.spy(templates, "TemplateResponse")

        response = test_client.get("/non-existent-page")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        template_spy.assert_called_once()
        _, kwargs = template_spy.call_args
        assert kwargs.get("name") == "404.html.j2"

        sep_app.dependency_overrides = {}

    @pytest.mark.parametrize(
        ("exception_cls", "expected_status", "expected_detail"),
        [
            pytest.param(
                HTTPServiceUnavailableException,
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Service Unavailable",
                id="503",
            ),
            pytest.param(
                HTTPBadGatewayException,
                status.HTTP_502_BAD_GATEWAY,
                "Bad Gateway",
                id="502",
            ),
        ],
    )
    def test_json_exception_handler(
        self,
        mocker,
        dummy_context,
        test_client,
        exception_cls,
        expected_status,
        expected_detail,
    ):
        """Assert gateway exceptions return JSON instead of redirecting."""
        mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=exception_cls(),
        )

        response = test_client.get("/", follow_redirects=False)

        assert response.status_code == expected_status
        assert response.json()["detail"] == expected_detail

    def test_404_error_unauthenticated(self, regular_user, test_client):
        """Test 404 errors redirects to the login page for unauthenticated users."""
        non_existent_path = "/non-existent-page"
        response = test_client.get(non_existent_path, follow_redirects=False)
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == f"/login?next={non_existent_path}"
        assert f'{sep_settings.SESSION.COOKIE_NAME}=""' in response.headers.get(
            "set-cookie", ""
        )

    def test_request_validation_error_handler_redirects_with_flash(
        self, mocker, dummy_context, test_client
    ):
        """Form-binding 422s become flash messages + 303 back to the form."""
        validation_errors = [
            {
                "type": "less_than_equal",
                "loc": ("body", "DEST_PORT"),
                "msg": "Input should be less than or equal to 65535",
                "input": "99999",
            },
            {
                "type": "none_required",
                "loc": ("body", "DEST_PORT"),
                "msg": "Input should be None",
                "input": "99999",
            },
        ]
        mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=RequestValidationError(validation_errors),
        )
        from_validation_error_mock = mocker.patch(
            "app.sep.main.messages.from_validation_error"
        )
        fake_referer = "/archives/"

        response = test_client.get(
            "/", headers={"Referer": fake_referer}, follow_redirects=False
        )

        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == fake_referer
        from_validation_error_mock.assert_called_once()
        call_kwargs = from_validation_error_mock.call_args.kwargs
        assert "none_required" in call_kwargs["exclude_types"]

    def test_request_validation_error_handler_bearer_returns_json(
        self, mocker, dummy_context, test_client
    ):
        """Bearer-authenticated callers keep the JSON 422 shape."""
        validation_errors = [
            {
                "type": "less_than_equal",
                "loc": ("body", "DEST_PORT"),
                "msg": "Input should be less than or equal to 65535",
                "input": "99999",
            },
        ]
        mocker.patch(
            "app.sep.main.templates.TemplateResponse",
            side_effect=RequestValidationError(validation_errors),
        )

        response = test_client.get(
            "/",
            headers={"Authorization": "Bearer any-token"},
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        # JSON serialization turns the ``loc`` tuple into a list.
        expected = [{**e, "loc": list(e["loc"])} for e in validation_errors]
        assert response.json()["detail"] == expected


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
        [("snippets", "/snippets/"), ("checksums", "/checksums/")],
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
    async def test_ui_guard_returns_503_for_non_enabled_states(
        self, guarded_client: TestClient, session, plugin_key, plugin_route, state
    ) -> None:
        """A non-protected plugin's UI route 503s whenever it is not ``ENABLED``."""
        session.add(AppState(app_key=plugin_key, lifecycle_state=state))
        await session.commit()

        response = guarded_client.get(plugin_route)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert plugin_key in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_child_ui_route_503s_when_parent_disabled(
        self, guarded_client: TestClient, session
    ) -> None:
        """Return 503 from a child app's UI route when its parent is disabled (gate uses parent_key)."""
        session.add(
            AppState(app_key="backup_mongo", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await session.commit()

        response = guarded_client.get("/backup_mongo/restores/")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "backup_mongo" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_inventory_ui_route_never_503s(
        self, guarded_client: TestClient, session
    ) -> None:
        """Inventory has no guard, so a disabled row never gates ``/inventory/``."""
        session.add(
            AppState(app_key="inventory", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await session.commit()

        response = guarded_client.get("/inventory/")

        assert response.status_code != status.HTTP_503_SERVICE_UNAVAILABLE

    @pytest.mark.parametrize(
        "route",
        [
            "/api/apps/atw/",
            "/api/apps/alert_troubleshooting/",
            "/alert-troubleshooting/",
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
            "/alert-troubleshooting/",
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

    def test_ui_mount_loop_guards_non_protected_plugins(self) -> None:
        """Every non-protected UI plugin route carries the app-state guard."""
        guarded_prefixes = {
            app.uri_path
            for app in get_app_registry()
            if app.key not in PROTECTED_APP_KEYS and app.jinja_router is not None
        }
        seen = set()
        for route in sep_app.routes:
            path = getattr(route, "path", "")
            for prefix in guarded_prefixes:
                if (
                    path == prefix or path.startswith(f"{prefix}/")
                ) and _route_has_app_guard(route):
                    seen.add(prefix)
        assert guarded_prefixes <= seen

    def test_inventory_ui_routes_are_not_guarded(self) -> None:
        """The protected ``inventory`` plugin's UI routes carry no app-state guard."""
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
