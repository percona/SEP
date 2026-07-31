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

"""Cover the settings HTTP surface under an active override restriction.

Drive a real ``build_settings_router`` through ``TestClient`` so the PATCH,
LIST, DETAIL and DELETE gates are exercised end to end, including the
criterion-7 rework that keeps a stale row deletable while its key is locked.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Annotated

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, settings
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.settings_override.api.routes import build_settings_router
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum, SettingOverride
from app.core.settings_override.registry import ReloadClassification
from app.core.utils import json_serializer
from app.inventory.config import inventory_settings, InventorySettings
from app.sep.config import sep_settings, SEPSettings
from app.tasks.config import tasks_settings, TasksSettings

ANNOTATIONS_KEY = "Settings.PMM__annotations_enabled"
LOGGING_KEY = "Settings.LOGGING"
SETTINGS_URL = f"/settings/{SettingClassEnum.SETTINGS.value}"
SEP_URL = f"/settings/{SettingClassEnum.SEP_SETTINGS.value}"
TASKS_URL = f"/settings/{SettingClassEnum.TASKS_SETTINGS.value}"
INVENTORY_URL = f"/settings/{SettingClassEnum.INVENTORY_SETTINGS.value}"


@pytest_asyncio.fixture(name="override_session")
async def override_session_fixture() -> AsyncIterator[AsyncSession]:
    """Provide an in-memory SQLite session with the override table."""
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


@pytest.fixture(name="client")
def client_fixture(override_session: AsyncSession) -> Iterator[TestClient]:
    """Yield a client whose router wires every locally-owned settings class."""

    async def get_session() -> AsyncSession:
        return override_session

    session_dep = Annotated[AsyncSession, Depends(get_session)]

    def allow_admin() -> None:
        return None

    classes = [
        (SettingClassEnum.SETTINGS, Settings, settings),
        (SettingClassEnum.SEP_SETTINGS, SEPSettings, sep_settings),
        (SettingClassEnum.TASKS_SETTINGS, TasksSettings, tasks_settings),
        (SettingClassEnum.INVENTORY_SETTINGS, InventorySettings, inventory_settings),
    ]
    router = build_settings_router(
        classes=classes,
        session_dep=session_dep,
        admin_dep=Depends(allow_admin),
    )
    app = FastAPI()
    app.include_router(router, prefix="/settings")
    return TestClient(app, raise_server_exceptions=False)


async def _seed_row(session: AsyncSession, **kwargs: object) -> None:
    """Insert one override row straight through the manager, bypassing the API."""
    await SettingsOverrideManager.create(session, SettingOverride(**kwargs))


def _error_types(response_json: dict) -> set[str]:
    """Return the distinct ``type`` values of a structured 422 detail payload."""
    return {entry["type"] for entry in response_json["detail"]}


class TestRemotePassThrough:
    """Cover the proxy carrying another service's lockdown refusal back verbatim."""

    def test_upstream_refusal_reaches_the_caller_unchanged(
        self, override_session: AsyncSession
    ) -> None:
        """Assert an upstream 422 keeps its status and structured detail."""
        upstream_detail = [
            {
                "loc": ["body", "NOMAD__endpoint"],
                "msg": "Setting cannot be overridden from the API.",
                "type": "not_overridable",
            }
        ]

        class _RefusingRemoteAPI:
            """Stand in for the Tasks service refusing a withheld key."""

            async def patch(self, path: str, **kwargs: object) -> None:
                """Raise the 422 the owning service's gate would return."""
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=upstream_detail,
                )

        async def get_session() -> AsyncSession:
            return override_session

        async def get_remote_api() -> _RefusingRemoteAPI:
            return _RefusingRemoteAPI()

        router = build_settings_router(
            classes=[(SettingClassEnum.SETTINGS, Settings, settings)],
            session_dep=Annotated[AsyncSession, Depends(get_session)],
            admin_dep=Depends(lambda: None),
            remote_classes=[(SettingClassEnum.TASKS_SETTINGS, "/admin/settings")],
            remote_api_dep=Annotated[_RefusingRemoteAPI, Depends(get_remote_api)],
        )
        app = FastAPI()
        app.include_router(router, prefix="/settings")
        client = TestClient(app, raise_server_exceptions=False)

        response = client.patch(TASKS_URL, json={"NOMAD__endpoint": "http://evil:4646"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.json()["detail"] == upstream_detail


class TestPatchGate:
    """Cover the three PATCH guards under an active restriction."""

    def test_locked_top_level_key_is_rejected(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert a locked top-level field refuses an override with 422."""
        restrict(LOGGING_KEY)
        response = client.patch(
            SEP_URL, json={"INVENTORY_ENDPOINT": "https://evil.example.com"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert _error_types(response.json()) == {"not_overridable"}

    def test_locked_nested_key_is_rejected(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert a locked leaf under an open parent refuses an override with 422."""
        restrict(ANNOTATIONS_KEY)
        response = client.patch(
            SETTINGS_URL, json={"PMM__endpoint": "https://evil.example.com"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert _error_types(response.json()) == {"not_overridable"}

    def test_whole_locked_parent_is_rejected(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert a whole-object write to a partially open parent is refused."""
        restrict(ANNOTATIONS_KEY)
        response = client.patch(
            SETTINGS_URL, json={"PMM": {"annotations_enabled": True}}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert _error_types(response.json()) == {"not_overridable"}

    def test_locked_nested_key_under_locked_parent_is_rejected(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert a leaf under a fully locked parent is refused by the parent guard."""
        restrict(LOGGING_KEY)
        response = client.patch(TASKS_URL, json={"NOMAD__endpoint": "http://evil:4646"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert _error_types(response.json()) == {"not_overridable"}

    def test_allowed_top_level_key_is_applied(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert an allowed field still accepts an override and echoes it HOT."""
        restrict(LOGGING_KEY)
        response = client.patch(SETTINGS_URL, json={"LOGGING": "INFO"})
        assert response.status_code == status.HTTP_200_OK
        applied = response.json()[0]
        assert applied["key"] == "LOGGING"
        assert applied["reload"] == ReloadClassification.HOT.value

    def test_allowed_nested_key_is_applied(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert an allowed leaf still accepts an override and echoes it HOT."""
        restrict(ANNOTATIONS_KEY)
        response = client.patch(SETTINGS_URL, json={"PMM__annotations_enabled": True})
        assert response.status_code == status.HTTP_200_OK
        applied = response.json()[0]
        assert applied["key"] == "PMM__annotations_enabled"
        assert applied["reload"] == ReloadClassification.HOT.value

    def test_inventory_router_exposes_nothing(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert the third service, which declares no HOT field, refuses writes."""
        restrict(LOGGING_KEY)
        response = client.patch(INVENTORY_URL, json={"UVICORN_PORT": 9999})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert _error_types(response.json()) == {"not_overridable"}


class TestPatchUnrestricted:
    """Assert the default restriction leaves every PATCH status unchanged."""

    def test_top_level_key_is_applied(self, client: TestClient) -> None:
        """Assert an unrestricted deployment still accepts the locked-down key."""
        response = client.patch(
            SEP_URL, json={"INVENTORY_ENDPOINT": "https://inventory.example.com"}
        )
        assert response.status_code == status.HTTP_200_OK

    def test_nested_key_is_applied(self, client: TestClient) -> None:
        """Assert an unrestricted deployment still accepts the locked-down leaf."""
        response = client.patch(
            SETTINGS_URL, json={"PMM__endpoint": "https://pmm.example.com"}
        )
        assert response.status_code == status.HTTP_200_OK


class TestReporting:
    """Cover what LIST and DETAIL report while the restriction is active."""

    def test_detail_reports_locked_leaf_as_not_overridable(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert DETAIL reports a locked leaf as not overridable."""
        restrict(ANNOTATIONS_KEY)
        response = client.get(f"{SETTINGS_URL}/PMM__endpoint")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["reload"] == (ReloadClassification.NOT_OVERRIDABLE.value)

    def test_detail_reports_allowed_leaf_as_hot(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert DETAIL still reports an allowed leaf as HOT."""
        restrict(ANNOTATIONS_KEY)
        response = client.get(f"{SETTINGS_URL}/PMM__annotations_enabled")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["reload"] == ReloadClassification.HOT.value

    def test_list_reports_the_gated_classification(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert LIST reports locked and allowed fields with their gated reload."""
        restrict("SEPSettings.SYNC_REFRESH_TIME")
        response = client.get("/settings/")
        assert response.status_code == status.HTTP_200_OK
        groups = {group["setting_class"]: group for group in response.json()["groups"]}
        reloads = {
            field["key"]: field["reload"]
            for field in groups[SettingClassEnum.SEP_SETTINGS.value]["settings"]
        }
        assert reloads["INVENTORY_ENDPOINT"] == (
            ReloadClassification.NOT_OVERRIDABLE.value
        )
        assert reloads["SYNC_REFRESH_TIME"] == ReloadClassification.HOT.value


class TestDeleteGate:
    """Cover the criterion-7 rework: stale rows stay deletable, absent rows 409."""

    @pytest.mark.asyncio
    async def test_locked_key_with_row_is_deleted(
        self,
        client: TestClient,
        override_session: AsyncSession,
        restrict: Callable[..., None],
    ) -> None:
        """Assert a stale row for a now-locked key is removable."""
        await _seed_row(
            override_session,
            setting_class=SettingClassEnum.SEP_SETTINGS,
            key="INVENTORY_ENDPOINT",
            value="https://stale.example.com",
            is_active=True,
        )
        restrict(LOGGING_KEY)
        response = client.delete(f"{SEP_URL}/INVENTORY_ENDPOINT")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert (
            await SettingsOverrideManager.count(
                override_session,
                setting_class=SettingClassEnum.SEP_SETTINGS,
                key="INVENTORY_ENDPOINT",
            )
            == 0
        )

    def test_locked_key_without_row_conflicts(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert deleting a locked key with nothing to delete reports a conflict."""
        restrict(LOGGING_KEY)
        response = client.delete(f"{SEP_URL}/INVENTORY_ENDPOINT")
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_statically_locked_key_with_row_still_conflicts(
        self,
        client: TestClient,
        restrict: Callable[..., None],
    ) -> None:
        """Assert an explicitly not-overridable field keeps its 409 answer."""
        restrict("SEPSettings.DIAGNOSTICS_DELIVERY")
        response = client.delete(f"{SEP_URL}/DIAGNOSTICS_DELIVERY")
        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.asyncio
    async def test_row_under_fully_locked_parent_is_deleted(
        self,
        client: TestClient,
        override_session: AsyncSession,
        restrict: Callable[..., None],
    ) -> None:
        """Assert a stale leaf row survives its parent becoming unaddressable."""
        await _seed_row(
            override_session,
            setting_class=SettingClassEnum.TASKS_SETTINGS,
            key="NOMAD__timeout",
            value=30,
            is_active=True,
        )
        restrict(LOGGING_KEY)
        response = client.delete(f"{TASKS_URL}/NOMAD__timeout")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert (
            await SettingsOverrideManager.count(
                override_session,
                setting_class=SettingClassEnum.TASKS_SETTINGS,
                key="NOMAD__timeout",
            )
            == 0
        )

    def test_unrestricted_delete_of_missing_row_is_idempotent(
        self, client: TestClient
    ) -> None:
        """Assert the default keeps DELETE idempotent for an overridable key."""
        response = client.delete(f"{SEP_URL}/INVENTORY_ENDPOINT")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.asyncio
    async def test_fully_locked_parent_with_row_is_deleted(
        self,
        client: TestClient,
        override_session: AsyncSession,
        restrict: Callable[..., None],
    ) -> None:
        """Assert a whole-parent row survives every leaf beneath it being withheld."""
        await _seed_row(
            override_session,
            setting_class=SettingClassEnum.TASKS_SETTINGS,
            key="NOMAD",
            value={"timeout": 30},
            is_active=True,
        )
        restrict(LOGGING_KEY)
        response = client.delete(f"{TASKS_URL}/NOMAD")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert (
            await SettingsOverrideManager.count(
                override_session,
                setting_class=SettingClassEnum.TASKS_SETTINGS,
                key="NOMAD",
            )
            == 0
        )

    def test_fully_locked_parent_without_row_conflicts(
        self, client: TestClient, restrict: Callable[..., None]
    ) -> None:
        """Assert a withheld parent with nothing to remove reports a conflict."""
        restrict(LOGGING_KEY)
        response = client.delete(f"{TASKS_URL}/NOMAD")
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_unrestricted_whole_parent_delete_is_rejected(
        self, client: TestClient
    ) -> None:
        """Assert the default keeps whole-parent deletion a 422, not a conflict."""
        response = client.delete(f"{TASKS_URL}/NOMAD")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert _error_types(response.json()) == {"not_overridable"}
