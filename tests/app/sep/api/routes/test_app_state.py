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

"""Tests for the admin app-state API at ``/api/admin/apps``."""

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.models import CasdoorUser
from app.sep.config import sep_settings
from app.sep.crud import AppStateManager
from app.sep.deps import (
    get_api_authenticated_user,
    get_current_user,
    get_session,
    require_bearer_for_unsafe_methods,
    validate_csrf,
)
from app.sep.main import sep_app
from app.sep.models import AppState


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
    async with async_session_maker() as session:
        yield session


@pytest.fixture(name="api_admin_client")
def api_admin_client_fixture(
    admin_user: CasdoorUser, override_session: AsyncSession
) -> Iterator[TestClient]:
    """Yield an admin-authenticated client with the Bearer gate satisfied."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture(name="api_non_admin_client")
def api_non_admin_client_fixture(
    regular_user: CasdoorUser, override_session: AsyncSession
) -> Iterator[TestClient]:
    """Yield a non-admin client with the in-memory SEP session."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture(name="api_admin_cookie_client")
def api_admin_cookie_client_fixture(
    admin_user: CasdoorUser, override_session: AsyncSession
) -> Iterator[TestClient]:
    """Yield a cookie-authenticated admin with the Bearer gate left intact."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture(name="api_unauthenticated_client")
def api_unauthenticated_client_fixture(
    override_session: AsyncSession,
) -> Iterator[TestClient]:
    """Yield an unauthenticated client — admin calls should 401 (JSON)."""
    sep_app.dependency_overrides = {}
    sep_app.dependency_overrides[get_session] = lambda: override_session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.mark.asyncio
class TestListApps:
    """Tests for ``GET /api/admin/apps/``."""

    async def test_lists_every_configured_plugin(
        self, api_admin_client: TestClient
    ) -> None:
        """Returns one entry per ``SEP.PLUGINS`` entry with the expected shape."""
        response = api_admin_client.get("/api/admin/apps/")
        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert len(payload) == len(sep_settings.PLUGINS)
        entry = payload[0]
        assert set(entry) == {
            "app_key",
            "name",
            "enabled",
            "toggleable",
            "uri_path",
            "css_class",
            "sidebar",
            "has_api_router",
        }

    async def test_inventory_is_not_toggleable_and_enabled(
        self, api_admin_client: TestClient
    ) -> None:
        """The protected ``inventory`` app reports enabled, non-toggleable."""
        response = api_admin_client.get("/api/admin/apps/")
        inventory = next(e for e in response.json() if e["app_key"] == "inventory")
        assert inventory["toggleable"] is False
        assert inventory["enabled"] is True

    async def test_reflects_seeded_state(
        self, api_admin_client: TestClient, override_session: AsyncSession
    ) -> None:
        """A non-protected app reflects its DB ``enabled`` value."""
        override_session.add(AppState(app_key="snippets", enabled=True))
        await override_session.commit()

        response = api_admin_client.get("/api/admin/apps/")
        snippets = next(e for e in response.json() if e["app_key"] == "snippets")
        assert snippets["enabled"] is True
        assert snippets["toggleable"] is True

    async def test_non_admin_returns_403(
        self, api_non_admin_client: TestClient
    ) -> None:
        """A non-admin user is rejected with 403."""
        response = api_non_admin_client.get("/api/admin/apps/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_unauthenticated_returns_json_401(
        self, api_unauthenticated_client: TestClient
    ) -> None:
        """An unauthenticated GET responds with a JSON 401, not an HTML redirect."""
        response = api_unauthenticated_client.get(
            "/api/admin/apps/", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
class TestUpdateAppState:
    """Tests for ``PUT /api/admin/apps/{app_key}/state``."""

    async def test_disable_then_enable(
        self, api_admin_client: TestClient, override_session: AsyncSession
    ) -> None:
        """Toggling a configured app updates the row and echoes the new state."""
        override_session.add(AppState(app_key="snippets", enabled=True))
        await override_session.commit()

        response = api_admin_client.put(
            "/api/admin/apps/snippets/state", json={"enabled": False}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"app_key": "snippets", "enabled": False}
        assert await AppStateManager.is_enabled(override_session, "snippets") is False

        response = api_admin_client.put(
            "/api/admin/apps/snippets/state", json={"enabled": True}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["enabled"] is True

    async def test_toggle_configured_app_without_row_creates_it(
        self, api_admin_client: TestClient, override_session: AsyncSession
    ) -> None:
        """A configured app with no row yet is created on toggle (no 404)."""
        response = api_admin_client.put(
            "/api/admin/apps/snippets/state", json={"enabled": False}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"app_key": "snippets", "enabled": False}
        assert await AppStateManager.is_enabled(override_session, "snippets") is False

    async def test_concurrent_first_toggle_returns_idempotent_200(
        self,
        api_admin_client: TestClient,
        override_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A concurrent first toggle returns idempotent 200, never a 400.

        Simulates the TOCTOU race on a configured-but-not-yet-seeded plugin: a
        concurrent winner has already committed the ``snippets`` row, but this
        request's ``get_or_create`` existence check ran before that commit.
        ``AppStateManager.first`` is patched to return ``None`` on its first
        invocation (the existence check) and delegate afterwards (the refetch).
        """
        override_session.add(AppState(app_key="snippets", enabled=True))
        await override_session.commit()

        original_first = AppStateManager.first.__func__
        calls = {"count": 0}

        async def first_returns_none_then_delegates(cls, *args, **kwargs):  # noqa: ANN
            calls["count"] += 1
            if calls["count"] == 1:
                return None
            return await original_first(cls, *args, **kwargs)

        monkeypatch.setattr(
            AppStateManager,
            "first",
            classmethod(first_returns_none_then_delegates),
        )

        response = api_admin_client.put(
            "/api/admin/apps/snippets/state", json={"enabled": False}
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"app_key": "snippets", "enabled": False}
        assert await AppStateManager.is_enabled(override_session, "snippets") is False

    async def test_protected_app_returns_409(
        self, api_admin_client: TestClient
    ) -> None:
        """Toggling the protected ``inventory`` app returns 409."""
        response = api_admin_client.put(
            "/api/admin/apps/inventory/state", json={"enabled": False}
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert "protected" in response.json()["detail"].lower()

    async def test_unknown_key_returns_404(self, api_admin_client: TestClient) -> None:
        """Toggling a key that matches no configured plugin returns 404."""
        response = api_admin_client.put(
            "/api/admin/apps/nonexistent/state", json={"enabled": False}
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_missing_enabled_returns_422(
        self, api_admin_client: TestClient
    ) -> None:
        """An empty body fails ``AppStateWrite`` validation."""
        response = api_admin_client.put("/api/admin/apps/snippets/state", json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_null_enabled_returns_422(self, api_admin_client: TestClient) -> None:
        """A null ``enabled`` value fails validation."""
        response = api_admin_client.put(
            "/api/admin/apps/snippets/state", json={"enabled": None}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_non_admin_returns_403(
        self, api_non_admin_client: TestClient
    ) -> None:
        """A non-admin user cannot toggle app state."""
        response = api_non_admin_client.put(
            "/api/admin/apps/snippets/state", json={"enabled": False}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_unauthenticated_returns_401(
        self, api_unauthenticated_client: TestClient
    ) -> None:
        """An unauthenticated PUT responds with a JSON 401."""
        response = api_unauthenticated_client.put(
            "/api/admin/apps/snippets/state",
            json={"enabled": False},
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")

    async def test_cookie_admin_without_bearer_returns_401(
        self, api_admin_cookie_client: TestClient
    ) -> None:
        """Cookie-authenticated admin cannot PUT without a Bearer header (CSRF defense)."""
        response = api_admin_cookie_client.put(
            "/api/admin/apps/snippets/state", json={"enabled": False}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_cookie_admin_can_still_read(
        self, api_admin_cookie_client: TestClient
    ) -> None:
        """GET listing remains accessible via cookie auth — only PUT needs Bearer."""
        response = api_admin_cookie_client.get("/api/admin/apps/")
        assert response.status_code == status.HTTP_200_OK
