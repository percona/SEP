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

"""SEP-1493: tests for the Inventory settings REST API and override bootstrap."""

from collections.abc import Iterator

import pytest
from fastapi import status
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.testclient import TestClient

from app.api.deps import get_current_user
from app.core.settings_override.cache import build_snapshot
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum, SettingOverride
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.inventory.config import inventory_settings, InventorySettings
from app.inventory.deps import get_session
from app.inventory.main import inventory_app
from app.models import CasdoorUser


@pytest.fixture(name="admin_client")
def admin_client_fixture(
    admin_user: CasdoorUser, session: AsyncSession
) -> Iterator[TestClient]:
    """Yield an admin-authenticated Inventory TestClient bound to the test session."""
    inventory_app.dependency_overrides[get_current_user] = lambda: admin_user
    inventory_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(inventory_app, raise_server_exceptions=False)
    inventory_app.dependency_overrides = {}


@pytest.fixture(name="non_admin_client")
def non_admin_client_fixture(
    regular_user: CasdoorUser, session: AsyncSession
) -> Iterator[TestClient]:
    """Yield a non-admin Inventory TestClient bound to the test session."""
    inventory_app.dependency_overrides[get_current_user] = lambda: regular_user
    inventory_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(inventory_app, raise_server_exceptions=False)
    inventory_app.dependency_overrides = {}


class TestInventorySettingsBootstrap:
    """The Inventory override framework is wired end-to-end."""

    def test_proxy_is_overridable(self) -> None:
        """``inventory_settings`` is an override-aware proxy, not a plain lazy one."""
        assert isinstance(inventory_settings, OverridableSettingsProxy)

    def test_enum_member_matches_class_name(self) -> None:
        """The new enum member's value equals the Pydantic class name."""
        assert SettingClassEnum.INVENTORY_SETTINGS.value == InventorySettings.__name__

    @pytest.mark.asyncio
    async def test_non_hot_override_row_is_skipped(self, session: AsyncSession) -> None:
        """A top-level row for a non-HOT field is skipped by the snapshot builder.

        ``InventorySettings`` ships no HOT field yet, so an override row must not
        leak into the snapshot -- the plumbing is wired but the field stays
        read-only until one is promoted.
        """
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.INVENTORY_SETTINGS,
                key="UVICORN_PORT",
                value=9999,
                is_active=True,
            ),
        )
        snapshot = await build_snapshot(session, InventorySettings)
        assert "UVICORN_PORT" not in snapshot


@pytest.mark.asyncio
class TestInventorySettingsRouter:
    """The admin-gated Inventory settings router lists ``InventorySettings``."""

    async def test_list_returns_inventory_class(self, admin_client: TestClient) -> None:
        """LIST exposes exactly the ``InventorySettings`` group."""
        response = admin_client.get("/admin/settings/")
        assert response.status_code == status.HTTP_200_OK
        classes = {g["setting_class"] for g in response.json()["groups"]}
        assert classes == {SettingClassEnum.INVENTORY_SETTINGS.value}

    async def test_get_field_returns_metadata(self, admin_client: TestClient) -> None:
        """GET on a single field returns its metadata."""
        response = admin_client.get("/admin/settings/InventorySettings/UVICORN_PORT")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["setting_class"] == (
            SettingClassEnum.INVENTORY_SETTINGS.value
        )

    async def test_non_admin_list_forbidden(self, non_admin_client: TestClient) -> None:
        """A non-admin caller is rejected from the admin-gated LIST."""
        response = non_admin_client.get("/admin/settings/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_non_admin_patch_forbidden(
        self, non_admin_client: TestClient
    ) -> None:
        """A non-admin caller cannot PATCH settings."""
        response = non_admin_client.patch(
            "/admin/settings/InventorySettings",
            json={"UVICORN_PORT": 9999},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_patch_non_hot_field_rejected(self, admin_client: TestClient) -> None:
        """No HOT field exists yet, so any PATCH is rejected as NOT_OVERRIDABLE."""
        response = admin_client.patch(
            "/admin/settings/InventorySettings",
            json={"UVICORN_PORT": 9999},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
