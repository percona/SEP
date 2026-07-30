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

"""Tests for the public navigation app-listing API at ``/api/apps``."""

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.sep.api.routes.apps import build_navigation_react_route
from app.sep.apps.framework.base import BaseApp
from app.sep.apps.framework.registry import AppRegistry, get_app_registry
from app.sep.deps import (
    get_api_authenticated_user,
    get_current_user,
    get_session,
    validate_csrf,
)
from app.sep.main import sep_app
from app.sep.models import AppLifecycleEnum, AppState


def _synthetic_app(key: str, *, requires_apps: tuple[str, ...] = ()) -> BaseApp:
    """Build a minimal top-level ``BaseApp`` carrying ``requires_apps``.

    Used to inject dependency shapes the real registry does not have (an app with
    two direct dependencies, or a three-hop chain) so the endpoint projection can
    be exercised against them.

    :param key: The app key.
    :param requires_apps: The direct dependency keys.
    :return: The constructed app.
    """
    return BaseApp(
        key=key,
        name=key,
        display_name=key,
        uri_path=f"/{key}",
        requires_apps=requires_apps,
    )


@pytest_asyncio.fixture(name="override_session")
async def override_session_fixture() -> AsyncIterator[AsyncSession]:
    """Provide an in-memory SQLite SEP session pre-loaded with all tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    try:
        async with async_session_maker() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture(name="api_user_client")
def api_user_client_fixture(
    regular_user: CasdoorUser, override_session: AsyncSession
) -> Iterator[TestClient]:
    """Yield an authenticated (non-admin) client with the in-memory SEP session."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture(name="api_unauthenticated_client")
def api_unauthenticated_client_fixture(
    override_session: AsyncSession,
) -> Iterator[TestClient]:
    """Yield an unauthenticated client — the listing should 401 (JSON)."""
    sep_app.dependency_overrides = {}
    sep_app.dependency_overrides[get_session] = lambda: override_session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.mark.asyncio
class TestListAppsForNavigation:
    """Tests for ``GET /api/apps/``."""

    async def test_any_authenticated_user_gets_the_listing(
        self, api_user_client: TestClient
    ) -> None:
        """A non-admin authenticated user receives the public projection."""
        response = api_user_client.get("/api/apps/")
        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert len(payload) == len(get_app_registry().keys())
        assert set(payload[0]) == {
            "app_key",
            "enabled",
            "sidebar",
            "uri_path",
            "display_name",
            "custom_ui",
            "group",
            "nav_order",
            "react_route",
            "nav_icon",
            "blocking_dependencies",
        }

    async def test_additive_fields_carry_registry_values(
        self, api_user_client: TestClient
    ) -> None:
        """Carry ``display_name`` and a boolean ``custom_ui`` flag on every entry."""
        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}
        for entry in entries.values():
            assert entry["display_name"]
            assert isinstance(entry["custom_ui"], bool)
        assert entries["atw"]["custom_ui"] is True

    async def test_group_and_nav_order_carry_registry_values(
        self, api_user_client: TestClient
    ) -> None:
        """Carry ``group``/``nav_order`` values from the plugin registry."""
        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}
        registry = get_app_registry()

        for app_key, entry in entries.items():
            definition = registry.get(app_key)
            assert entry["group"] == definition.group
            assert entry["nav_order"] == definition.nav_order

    async def test_react_route_and_nav_icon_carry_registry_values(
        self, api_user_client: TestClient
    ) -> None:
        """Carry ``react_route`` (concrete default) and ``nav_icon`` per entry."""
        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}
        registry = get_app_registry()

        for app_key, entry in entries.items():
            definition = registry.get(app_key)
            assert entry["react_route"] == build_navigation_react_route(
                app_key, definition.react_route
            )
            assert entry["nav_icon"] == definition.nav_icon

    async def test_default_react_route_emitted_concrete(
        self, api_user_client: TestClient
    ) -> None:
        """Emit ``/apps/<key>`` for an app with no ``react_route`` override."""
        response = api_user_client.get("/api/apps/")
        checksums = next(e for e in response.json() if e["app_key"] == "checksums")
        assert checksums["react_route"] == "/apps/checksums"

    @pytest.mark.parametrize(
        ("app_key", "expected_route"),
        [
            ("tasks", "/apps/tasks"),
            ("alerts", "/apps/alerts/templates"),
            ("backup_mongo", "/apps/backups/mongodb"),
            ("backup_pg", "/apps/backups/postgresql"),
            ("report", "/apps/reports"),
        ],
    )
    async def test_declared_react_routes_are_normalized_under_apps_namespace(
        self, api_user_client: TestClient, app_key: str, expected_route: str
    ) -> None:
        """Emit declared routes after normalizing them under ``/apps``."""
        response = api_user_client.get("/api/apps/")
        entry = next(e for e in response.json() if e["app_key"] == app_key)
        assert entry["react_route"] == expected_route

    async def test_child_enabled_follows_parent(
        self, api_user_client: TestClient, override_session: AsyncSession
    ) -> None:
        """Derive a child app's reported ``enabled`` from the parent's state, not its own key.

        Disabling the parent must flip the child to disabled even though the
        child's own key never owns a row — a ``key``-based lookup would default it
        to enabled, so this pins the ``state_key`` derivation on the nav surface.
        """
        override_session.add(
            AppState(app_key="mysql_backups", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await override_session.commit()

        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}
        assert entries["mysql_backups"]["enabled"] is False
        assert entries["mysql_backups/restore"]["enabled"] is False
        assert entries["backup_mongo"]["enabled"] is True
        assert entries["backup_mongo/restore"]["enabled"] is True

    async def test_inventory_reported_enabled(
        self, api_user_client: TestClient
    ) -> None:
        """The protected ``inventory`` app is always reported enabled."""
        response = api_user_client.get("/api/apps/")
        inventory = next(e for e in response.json() if e["app_key"] == "inventory")
        assert inventory["enabled"] is True

    @pytest.mark.parametrize(
        "state",
        [
            AppLifecycleEnum.DISABLED,
            AppLifecycleEnum.DISABLING,
            AppLifecycleEnum.ENABLING,
        ],
    )
    async def test_non_enabled_plugin_reported_disabled(
        self,
        api_user_client: TestClient,
        override_session: AsyncSession,
        state: AppLifecycleEnum,
    ) -> None:
        """A non-protected plugin in any non-ENABLED state reports ``enabled=False``.

        The public navigation listing keeps its ``enabled``-only shape — it does
        not surface ``lifecycle_state``.
        """
        override_session.add(AppState(app_key="snippets", lifecycle_state=state))
        await override_session.commit()

        response = api_user_client.get("/api/apps/")
        snippets = next(e for e in response.json() if e["app_key"] == "snippets")
        assert snippets["enabled"] is False
        assert "lifecycle_state" not in snippets

    async def test_atw_reported_disabled_when_snippets_disabled(
        self, api_user_client: TestClient, override_session: AsyncSession
    ) -> None:
        """Atw reports ``enabled=False`` when the ``snippets`` app it requires is disabled.

        This pins the cross-app dependency on the nav surface: atw owns an
        ``ENABLED`` row (or none) yet is projected disabled because a required
        app is off, so the shell hides it.
        """
        override_session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await override_session.commit()

        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}
        assert entries["snippets"]["enabled"] is False
        assert entries["atw"]["enabled"] is False
        # atw is dependency-disabled -> it names snippets as the blocker, while
        # snippets is self-disabled -> it reports no blocker (generic splash).
        assert entries["atw"]["blocking_dependencies"] == ["snippets"]
        assert entries["snippets"]["blocking_dependencies"] == []

    async def test_atw_reported_enabled_when_snippets_enabled(
        self, api_user_client: TestClient
    ) -> None:
        """Atw reports ``enabled=True`` when snippets is enabled (no regression)."""
        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}
        assert entries["snippets"]["enabled"] is True
        assert entries["atw"]["enabled"] is True
        assert entries["atw"]["blocking_dependencies"] == []

    async def test_alert_troubleshooting_reported_disabled_when_snippets_disabled(
        self, api_user_client: TestClient, override_session: AsyncSession
    ) -> None:
        """Report Alert Troubleshooting disabled with snippets as its blocker."""
        override_session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await override_session.commit()

        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}

        assert entries["alert_troubleshooting"]["enabled"] is False
        assert entries["alert_troubleshooting"]["blocking_dependencies"] == ["snippets"]

    async def test_alert_troubleshooting_reported_enabled_when_snippets_enabled(
        self, api_user_client: TestClient
    ) -> None:
        """Report Alert Troubleshooting enabled when snippets is enabled."""
        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}

        assert entries["alert_troubleshooting"]["enabled"] is True
        assert entries["alert_troubleshooting"]["blocking_dependencies"] == []

    async def test_self_disabled_app_reports_no_blocking_dependency(
        self, api_user_client: TestClient, override_session: AsyncSession
    ) -> None:
        """Report no blocker for a directly-disabled app so the generic splash shows.

        With atw's own state disabled (regardless of snippets), the disablement is
        self-driven, so ``blocking_dependencies`` stays empty even though atw
        declares ``requires_apps=("snippets",)``.
        """
        override_session.add(
            AppState(app_key="atw", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await override_session.commit()

        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}
        assert entries["atw"]["enabled"] is False
        assert entries["atw"]["blocking_dependencies"] == []

    @pytest.mark.parametrize(
        "state",
        [AppLifecycleEnum.DISABLING, AppLifecycleEnum.ENABLING],
    )
    async def test_transitional_dependency_populates_blocking_dependencies(
        self,
        api_user_client: TestClient,
        override_session: AsyncSession,
        state: AppLifecycleEnum,
    ) -> None:
        """Name a dependency mid-transition as the blocker, since only ENABLED is on.

        A dependency stuck in ``ENABLING``/``DISABLING`` is not effective-enabled,
        so a dependent app is projected disabled and must still name it.
        """
        override_session.add(AppState(app_key="snippets", lifecycle_state=state))
        await override_session.commit()

        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}
        assert entries["atw"]["enabled"] is False
        assert entries["atw"]["blocking_dependencies"] == ["snippets"]

    async def test_protected_app_reports_no_blocking_dependency(
        self, api_user_client: TestClient
    ) -> None:
        """Report an empty blocker list for the protected ``inventory`` app."""
        response = api_user_client.get("/api/apps/")
        inventory = next(e for e in response.json() if e["app_key"] == "inventory")
        assert inventory["blocking_dependencies"] == []

    async def test_multiple_blocking_dependencies_preserve_declaration_order(
        self,
        api_user_client: TestClient,
        override_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Emit every disabled direct dependency, in declaration order, through the API.

        The real registry has no app declaring two direct dependencies, so inject a
        synthetic registry to pin the projected list shape and ordering.
        """
        registry = AppRegistry(
            [
                _synthetic_app("a", requires_apps=("b", "c")),
                _synthetic_app("b"),
                _synthetic_app("c"),
            ]
        )
        monkeypatch.setattr(
            "app.sep.api.routes.apps.get_app_registry", lambda: registry
        )
        override_session.add(
            AppState(app_key="b", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        override_session.add(
            AppState(app_key="c", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await override_session.commit()

        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}
        assert entries["a"]["enabled"] is False
        assert entries["a"]["blocking_dependencies"] == ["b", "c"]

    async def test_transitive_disable_names_immediate_blocker_through_api(
        self,
        api_user_client: TestClient,
        override_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Name the immediate dependency, not the deep cause, in the API projection.

        With ``x -> y -> z`` and ``z`` disabled, ``x`` reports ``y`` (its immediate
        effective-disabled dependency) while ``y`` reports ``z``.
        """
        registry = AppRegistry(
            [
                _synthetic_app("x", requires_apps=("y",)),
                _synthetic_app("y", requires_apps=("z",)),
                _synthetic_app("z"),
            ]
        )
        monkeypatch.setattr(
            "app.sep.api.routes.apps.get_app_registry", lambda: registry
        )
        override_session.add(
            AppState(app_key="z", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        await override_session.commit()

        response = api_user_client.get("/api/apps/")
        entries = {e["app_key"]: e for e in response.json()}
        assert entries["x"]["blocking_dependencies"] == ["y"]
        assert entries["y"]["blocking_dependencies"] == ["z"]

    async def test_unauthenticated_returns_json_401(
        self, api_unauthenticated_client: TestClient
    ) -> None:
        """An unauthenticated GET responds with a JSON 401, not an HTML redirect."""
        response = api_unauthenticated_client.get("/api/apps/", follow_redirects=False)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")
