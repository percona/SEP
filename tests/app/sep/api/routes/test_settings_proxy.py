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

"""Tests for the SEP-level ``TasksSettings`` proxy (SEP-1330).

``TasksSettings`` storage lives in the Tasks sub-app, so the SEP settings router
registers it as a *remote* class: the LIST appends its group server-side and the
DETAIL / PATCH / DELETE paths dispatch to the Tasks API via ``get_tasks_api``.
These tests mock that dependency and assert aggregation, dispatch, the
4xx-passthrough / 5xx-502 error split, auth parity, and the unhappy paths.

Token forwarding (the proxied request carries the caller's Bearer token) is
covered by ``tests/app/sep/test_deps.py::TestGetTasksApi`` and not duplicated here.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.requests import RemoteAPI
from app.core.utils import json_serializer
from app.models import CasdoorUser
from app.sep.deps import (
    get_api_authenticated_user,
    get_current_user,
    get_session,
    get_tasks_api,
    require_bearer_for_unsafe_methods,
    validate_csrf,
)
from app.sep.main import sep_app

TASKS_KEY = "STALENESS_THRESHOLD_SECONDS"
REMOTE_BASE = "/admin/settings"


def _tasks_setting(value: Any = 3600, *, has_override: bool = False) -> dict[str, Any]:
    """Return a Tasks-group :class:`SettingResponse` payload as the proxy sees it."""
    return {
        "setting_class": "TasksSettings",
        "key": TASKS_KEY,
        "key_path": [TASKS_KEY],
        "value": value,
        "default_value": 3600,
        "type": "int",
        "reload": "hot",
        "description": "How long before a task is considered stale.",
        "is_secret": False,
        "is_complex": False,
        "has_override": has_override,
    }


def _tasks_list(settings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a remote LIST payload (``SettingsListResponse``) for the Tasks app."""
    return {
        "groups": [
            {
                "setting_class": "TasksSettings",
                "settings": [_tasks_setting()] if settings is None else settings,
            }
        ]
    }


@pytest_asyncio.fixture(name="override_session")
async def override_session_fixture() -> AsyncIterator[AsyncSession]:
    """Provide an in-memory SEP session pre-loaded with the override table."""
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


@pytest.fixture(name="mock_tasks")
def mock_tasks_fixture() -> Iterator[AsyncMock]:
    """Override ``get_tasks_api`` with an :class:`AsyncMock` Tasks API client."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides.pop(get_tasks_api, None)


@pytest.fixture(name="admin_client")
def admin_client_fixture(
    admin_user: CasdoorUser, override_session: AsyncSession, mock_tasks: AsyncMock
) -> Iterator[TestClient]:
    """Yield an admin client (Bearer gate satisfied) with the Tasks API mocked."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture(name="non_admin_client")
def non_admin_client_fixture(
    regular_user: CasdoorUser, override_session: AsyncSession, mock_tasks: AsyncMock
) -> Iterator[TestClient]:
    """Yield a non-admin client (admin gate should reject) with the Tasks API mocked."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture(name="cookie_admin_client")
def cookie_admin_client_fixture(
    admin_user: CasdoorUser, override_session: AsyncSession, mock_tasks: AsyncMock
) -> Iterator[TestClient]:
    """Yield a cookie-only admin client (Bearer gate intact) with the Tasks API mocked.

    ``require_bearer_for_unsafe_methods`` is deliberately left un-overridden so
    unsafe methods (PATCH / DELETE) without a Bearer header reject with 401.
    """
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


class TestListAggregation:
    """``GET /api/sep/admin/settings/`` aggregates the proxied Tasks group."""

    def test_appends_tasks_group_fetched_server_side(
        self, admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """Return the three local groups plus the Tasks group, fetched via the proxy."""
        mock_tasks.get.return_value = _tasks_list([_tasks_setting(has_override=True)])
        response = admin_client.get("/api/sep/admin/settings/")
        assert response.status_code == status.HTTP_200_OK
        classes = [g["setting_class"] for g in response.json()["groups"]]
        assert {"SEPSettings", "SnippetsSettings", "MessagesSettings"}.issubset(
            set(classes)
        )
        assert classes[-1] == "TasksSettings"
        mock_tasks.get.assert_awaited_once_with(f"{REMOTE_BASE}/")

    def test_empty_tasks_group_still_renders(
        self, admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """A Tasks group with no settings is appended without error."""
        mock_tasks.get.return_value = _tasks_list([])
        response = admin_client.get("/api/sep/admin/settings/")
        assert response.status_code == status.HTTP_200_OK
        tasks_group = next(
            g
            for g in response.json()["groups"]
            if g["setting_class"] == "TasksSettings"
        )
        assert tasks_group["settings"] == []

    def test_upstream_http_error_fails_closed_502(
        self, admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """A failed Tasks-group fetch fails the whole LIST with 502."""
        mock_tasks.get.side_effect = HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="tasks down"
        )
        response = admin_client.get("/api/sep/admin/settings/")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json() == {"detail": "tasks down"}

    def test_upstream_oserror_fails_closed_502(
        self, admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """A connection-level failure on the Tasks-group fetch becomes a 502."""
        mock_tasks.get.side_effect = OSError("connection refused")
        response = admin_client.get("/api/sep/admin/settings/")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json() == {"detail": "connection refused"}

    def test_upstream_shape_drift_returns_500(
        self, admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """An upstream payload that fails validation surfaces as 500, not 502."""
        mock_tasks.get.return_value = {
            "groups": [{"setting_class": "TasksSettings", "settings": [{"bad": "x"}]}]
        }
        response = admin_client.get("/api/sep/admin/settings/")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


class TestDispatch:
    """DETAIL / PATCH / DELETE dispatch to the Tasks API for the remote class."""

    def test_detail_dispatches_to_proxy(
        self, admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """``GET .../TasksSettings/{key}`` proxies to the Tasks API and validates."""
        mock_tasks.get.return_value = _tasks_setting(has_override=True)
        response = admin_client.get(
            f"/api/sep/admin/settings/TasksSettings/{TASKS_KEY}"
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["setting_class"] == "TasksSettings"
        assert body["key"] == TASKS_KEY
        mock_tasks.get.assert_awaited_once_with(
            f"{REMOTE_BASE}/TasksSettings/{TASKS_KEY}"
        )

    def test_patch_dispatches_to_proxy(
        self, admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """``PATCH .../TasksSettings`` forwards the body and validates the response."""
        new_value = 7200
        mock_tasks.patch.return_value = [
            _tasks_setting(value=new_value, has_override=True)
        ]
        response = admin_client.patch(
            "/api/sep/admin/settings/TasksSettings", json={TASKS_KEY: new_value}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["value"] == new_value
        mock_tasks.patch.assert_awaited_once_with(
            f"{REMOTE_BASE}/TasksSettings", json={TASKS_KEY: new_value}
        )

    def test_delete_dispatches_to_proxy(
        self, admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """``DELETE .../TasksSettings/{key}`` proxies and returns 204."""
        mock_tasks.delete.return_value = None
        response = admin_client.delete(
            f"/api/sep/admin/settings/TasksSettings/{TASKS_KEY}"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_tasks.delete.assert_awaited_once_with(
            f"{REMOTE_BASE}/TasksSettings/{TASKS_KEY}"
        )

    def test_patch_passes_through_upstream_422(
        self, admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """An upstream 422 keeps its status and ``detail`` (FE inline validation)."""
        mock_tasks.patch.side_effect = HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "loc": ["body", TASKS_KEY, "greater_than"],
                    "msg": "Input should be greater than 0",
                    "type": "greater_than",
                }
            ],
        )
        response = admin_client.patch(
            "/api/sep/admin/settings/TasksSettings", json={TASKS_KEY: 0}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.json()["detail"][0]["msg"] == "Input should be greater than 0"

    def test_detail_unknown_key_passes_through_upstream_404(
        self, admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """A key the Tasks app rejects passes back its 404, with no path escape.

        FastAPI's ``{key}`` path converter never matches ``/``, so a remote-path
        escape is impossible; the proxy forwards the key verbatim and the upstream
        404 is preserved (not masked as a 502).
        """
        mock_tasks.get.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown key"
        )
        response = admin_client.get(
            "/api/sep/admin/settings/TasksSettings/DOES_NOT_EXIST"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"detail": "unknown key"}
        mock_tasks.get.assert_awaited_once_with(
            f"{REMOTE_BASE}/TasksSettings/DOES_NOT_EXIST"
        )

    def test_local_class_is_not_proxied(
        self, admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """A PATCH to a local class hits the SEP DB and never touches the Tasks API."""
        response = admin_client.patch(
            "/api/sep/admin/settings/SEPSettings", json={"SYNC_REFRESH_TIME": 7}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["key"] == "SYNC_REFRESH_TIME"
        mock_tasks.patch.assert_not_awaited()
        mock_tasks.get.assert_not_awaited()


class TestAuthParity:
    """The remote paths inherit the same admin + Bearer gates as the local ones."""

    def test_non_admin_detail_forbidden(
        self, non_admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """A non-admin is rejected before the proxy runs."""
        response = non_admin_client.get(
            f"/api/sep/admin/settings/TasksSettings/{TASKS_KEY}"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_tasks.get.assert_not_awaited()

    def test_cookie_only_patch_unauthorized(
        self, cookie_admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """A cookie-only admin cannot PATCH the remote class (no Bearer -> 401)."""
        response = cookie_admin_client.patch(
            "/api/sep/admin/settings/TasksSettings", json={TASKS_KEY: 7200}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        mock_tasks.patch.assert_not_awaited()

    def test_cookie_only_delete_unauthorized(
        self, cookie_admin_client: TestClient, mock_tasks: AsyncMock
    ) -> None:
        """A cookie-only admin cannot DELETE the remote class (no Bearer -> 401)."""
        response = cookie_admin_client.delete(
            f"/api/sep/admin/settings/TasksSettings/{TASKS_KEY}"
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        mock_tasks.delete.assert_not_awaited()
