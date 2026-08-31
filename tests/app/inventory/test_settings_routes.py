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

"""Test the Inventory settings REST API and override bootstrap."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI, status
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.testclient import TestClient

from app import main as main_module
from app.api.deps import get_current_user, require_minimum_role_for_unsafe_methods
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.settings_override.cache import build_snapshot
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import (
    setting_class_token,
    SettingClassEnum,
    SettingOverride,
)
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.inventory.config import inventory_settings, InventorySettings
from app.inventory.deps import get_session
from app.inventory.main import inventory_app


@pytest.fixture(name="admin_client")
def admin_client_fixture(
    admin_user: CasdoorUser, session: AsyncSession
) -> Iterator[TestClient]:
    """Yield an admin-authenticated Inventory TestClient bound to the test session."""
    inventory_app.dependency_overrides[require_minimum_role_for_unsafe_methods] = (
        lambda: None
    )
    inventory_app.dependency_overrides[get_current_user] = lambda: admin_user
    inventory_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(inventory_app, raise_server_exceptions=False)
    inventory_app.dependency_overrides = {}


@pytest.fixture(name="non_admin_client")
def non_admin_client_fixture(
    regular_user: CasdoorUser, session: AsyncSession
) -> Iterator[TestClient]:
    """Yield a non-admin Inventory TestClient bound to the test session.

    The router-level gate is overridden so the refusal under test comes from the
    route's own ``IsAdminDep``, not from the gate that precedes it.
    """
    inventory_app.dependency_overrides[require_minimum_role_for_unsafe_methods] = (
        lambda: None
    )
    inventory_app.dependency_overrides[get_current_user] = lambda: regular_user
    inventory_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(inventory_app, raise_server_exceptions=False)
    inventory_app.dependency_overrides = {}


class TestInventorySettingsBootstrap:
    """The Inventory override framework is wired end-to-end."""

    def test_proxy_is_overridable(self) -> None:
        """Assert ``inventory_settings`` is an override-aware proxy, not a plain lazy one."""
        assert isinstance(inventory_settings, OverridableSettingsProxy)

    def test_enum_member_matches_class_name(self) -> None:
        """Assert the new enum member's value equals the Pydantic class name."""
        assert SettingClassEnum.INVENTORY_SETTINGS.value == InventorySettings.__name__

    @pytest.mark.asyncio
    async def test_non_hot_override_row_is_skipped(self, session: AsyncSession) -> None:
        """Assert a top-level row for a non-HOT field is skipped by the snapshot builder.

        ``InventorySettings`` ships no HOT field yet, so an override row must not
        leak into the snapshot -- the plumbing is wired but the field stays
        read-only until one is promoted.
        """
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(InventorySettings),
                key="UVICORN_PORT",
                value=9999,
                is_active=True,
            ),
        )
        snapshot = await build_snapshot(session, InventorySettings)
        assert "UVICORN_PORT" not in snapshot

    @pytest.mark.asyncio
    async def test_main_lifespan_enters_inventory_overrides(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Assert ``main_lifespan`` enters the Inventory override refresher once.

        Starlette's ``Mount`` never forwards the ``lifespan`` scope, so the
        ``INVENTORY_SETTINGS`` refresher must be wired into ``main_lifespan``
        via ``inventory_overrides_lifespan``.
        """
        entered = 0

        @asynccontextmanager
        async def _spy_inventory_overrides(_app: FastAPI) -> AsyncIterator[None]:
            nonlocal entered
            entered += 1
            yield

        async def _no_op_sep_startup() -> None:
            """Stub ``sep_startup`` so the test does not hit the real SEP DB."""

        @asynccontextmanager
        async def _no_op_lifespan(_app: FastAPI) -> AsyncIterator[None]:
            """Stub the SEP/Tasks lifespans so the test stays hermetic."""
            yield

        monkeypatch.setattr(main_module, "sep_startup", _no_op_sep_startup)
        monkeypatch.setattr(main_module, "sep_overrides_lifespan", _no_op_lifespan)
        monkeypatch.setattr(main_module, "tasks_lifespan", _no_op_lifespan)
        monkeypatch.setattr(
            main_module, "inventory_overrides_lifespan", _spy_inventory_overrides
        )
        monkeypatch.setattr(
            main_module, "validate_importable_settings", lambda *_args: None
        )

        async with main_module.main_lifespan(FastAPI()):
            assert entered == 1


@pytest.mark.asyncio
class TestInventorySettingsRouter:
    """The admin-gated Inventory settings router lists ``InventorySettings``."""

    async def test_list_returns_inventory_class(self, admin_client: TestClient) -> None:
        """Assert LIST exposes exactly the ``InventorySettings`` group."""
        response = admin_client.get("/admin/settings/")
        assert response.status_code == status.HTTP_200_OK
        classes = {g["setting_class"] for g in response.json()["groups"]}
        assert classes == {SettingClassEnum.INVENTORY_SETTINGS.value}

    async def test_get_field_returns_metadata(self, admin_client: TestClient) -> None:
        """Assert GET on a single field returns its metadata."""
        response = admin_client.get("/admin/settings/InventorySettings/UVICORN_PORT")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["setting_class"] == (
            SettingClassEnum.INVENTORY_SETTINGS.value
        )

    async def test_non_admin_list_forbidden(self, non_admin_client: TestClient) -> None:
        """Assert a non-admin caller is rejected from the admin-gated LIST."""
        response = non_admin_client.get("/admin/settings/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_non_admin_patch_forbidden(
        self, non_admin_client: TestClient
    ) -> None:
        """Assert a non-admin caller cannot PATCH settings."""
        response = non_admin_client.patch(
            "/admin/settings/InventorySettings",
            json={"UVICORN_PORT": 9999},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_patch_non_hot_field_rejected(self, admin_client: TestClient) -> None:
        """Assert any PATCH is rejected as NOT_OVERRIDABLE (no HOT field exists yet)."""
        response = admin_client.patch(
            "/admin/settings/InventorySettings",
            json={"UVICORN_PORT": 9999},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
