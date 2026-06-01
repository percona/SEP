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

"""Tests for the SEP settings REST API at ``/api/sep/admin/settings``."""

from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.settings_override.api import routes as settings_routes
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.registry import ReloadClassification
from app.core.utils import json_serializer
from app.models import CasdoorUser
from app.sep.config import sep_settings
from app.sep.deps import (
    get_api_authenticated_user,
    get_current_user,
    get_session,
    require_bearer_auth,
    validate_csrf,
)
from app.sep.main import sep_app
from app.sep.middleware.messages.config import messages_settings
from app.sep.snippets.config import snippets_settings


@pytest_asyncio.fixture(name="override_session")
async def override_session_fixture() -> AsyncIterator[AsyncSession]:
    """Provide an in-memory SQLite SEP session pre-loaded with the override table."""
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
    """Yield an admin-authenticated SEP TestClient with the in-memory SEP session."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    sep_app.dependency_overrides[require_bearer_auth] = lambda: None
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture(name="api_non_admin_client")
def api_non_admin_client_fixture(
    regular_user: CasdoorUser, override_session: AsyncSession
) -> Iterator[TestClient]:
    """Yield a non-admin SEP TestClient with the in-memory SEP session."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    sep_app.dependency_overrides[require_bearer_auth] = lambda: None
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture(name="api_admin_cookie_client")
def api_admin_cookie_client_fixture(
    admin_user: CasdoorUser, override_session: AsyncSession
) -> Iterator[TestClient]:
    """Yield an admin authenticated by cookie session (no Bearer header).

    The Bearer guard runs as in production; mutations should reject the
    client with 401 while reads succeed.
    """
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
    """Yield an unauthenticated SEP TestClient — settings calls should 401."""
    sep_app.dependency_overrides = {}
    sep_app.dependency_overrides[get_session] = lambda: override_session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


def _find_setting(
    payload: dict[str, Any], setting_class: str, key: str
) -> dict[str, Any]:
    """Locate one setting entry in the LIST response payload."""
    for group in payload["groups"]:
        if group["setting_class"] == setting_class:
            for entry in group["settings"]:
                if entry["key"] == key:
                    return entry
    raise AssertionError(f"setting {setting_class}/{key} not in payload")


@pytest.mark.asyncio
class TestSepSettingsList:
    """Tests for ``GET /api/sep/admin/settings/``."""

    async def test_returns_three_groups(self, api_admin_client: TestClient) -> None:
        """Returns one group per wired settings class on the SEP sub-app."""
        response = api_admin_client.get("/api/sep/admin/settings/")
        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        groups = {group["setting_class"] for group in payload["groups"]}
        assert groups == {
            SettingClassEnum.SEP_SETTINGS.value,
            SettingClassEnum.SNIPPETS_SETTINGS.value,
            SettingClassEnum.MESSAGES_SETTINGS.value,
        }

    async def test_lists_hot_and_not_overridable_entries(
        self, api_admin_client: TestClient
    ) -> None:
        """A SEPSettings group exposes HOT, NESTED_ONLY and NOT_OVERRIDABLE fields."""
        response = api_admin_client.get("/api/sep/admin/settings/")
        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        sep_entry = next(
            group
            for group in payload["groups"]
            if group["setting_class"] == SettingClassEnum.SEP_SETTINGS.value
        )
        reloads = {entry["reload"] for entry in sep_entry["settings"]}
        assert reloads == {
            ReloadClassification.HOT.value,
            ReloadClassification.NESTED_ONLY.value,
            ReloadClassification.NOT_OVERRIDABLE.value,
        }

    async def test_no_override_marks_has_override_false(
        self, api_admin_client: TestClient
    ) -> None:
        """A field with no override row reports ``has_override=False``."""
        response = api_admin_client.get("/api/sep/admin/settings/")
        sep_setting = _find_setting(
            response.json(), SettingClassEnum.SEP_SETTINGS.value, "SYNC_REFRESH_TIME"
        )
        assert sep_setting["has_override"] is False


@pytest.mark.asyncio
class TestSepSettingsGet:
    """Tests for ``GET /api/sep/admin/settings/{setting_class}/{key}``."""

    async def test_existing_field_returns_metadata(
        self, api_admin_client: TestClient
    ) -> None:
        """Returns a single setting's metadata and current value."""
        response = api_admin_client.get(
            "/api/sep/admin/settings/SEPSettings/SYNC_REFRESH_TIME"
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["key"] == "SYNC_REFRESH_TIME"
        assert body["setting_class"] == SettingClassEnum.SEP_SETTINGS.value
        assert body["reload"] == ReloadClassification.HOT.value
        assert body["has_override"] is False

    async def test_unknown_class_returns_422(
        self, api_admin_client: TestClient
    ) -> None:
        """FastAPI's enum validation rejects an unknown settings class with 422."""
        response = api_admin_client.get(
            "/api/sep/admin/settings/InventorySettings/SYNC_REFRESH_TIME"
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_unknown_key_returns_404(self, api_admin_client: TestClient) -> None:
        """An unknown key on a wired class returns 404."""
        response = api_admin_client.get(
            "/api/sep/admin/settings/SEPSettings/DOES_NOT_EXIST"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
class TestSepSettingsPatch:
    """Tests for ``PATCH /api/sep/admin/settings/{setting_class}``."""

    async def test_single_key_creates_override_row(
        self,
        api_admin_client: TestClient,
        override_session: AsyncSession,
    ) -> None:
        """Persisting one key creates exactly one row and reflects in next read."""
        new_value = 10
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SYNC_REFRESH_TIME": new_value},
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == 1
        assert body[0]["key"] == "SYNC_REFRESH_TIME"
        assert body[0]["value"] == new_value
        assert body[0]["has_override"] is True

        rows = await SettingsOverrideManager.list(
            override_session,
            setting_class=SettingClassEnum.SEP_SETTINGS,
        )
        assert len(rows) == 1
        assert rows[0].key == "SYNC_REFRESH_TIME"
        assert rows[0].value == new_value

    async def test_existing_override_is_updated(
        self,
        api_admin_client: TestClient,
        override_session: AsyncSession,
    ) -> None:
        """Patching an already-overridden key updates the row instead of inserting."""
        first_value = 10
        second_value = 20
        api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SYNC_REFRESH_TIME": first_value},
        )
        api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SYNC_REFRESH_TIME": second_value},
        )
        rows = await SettingsOverrideManager.list(
            override_session,
            setting_class=SettingClassEnum.SEP_SETTINGS,
            key="SYNC_REFRESH_TIME",
        )
        assert len(rows) == 1
        assert rows[0].value == second_value

    async def test_multiple_keys_persist_atomically(
        self, api_admin_client: TestClient
    ) -> None:
        """Patching three valid keys creates three rows, all visible on the next GET."""
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={
                "SYNC_REFRESH_TIME": 12,
                "ARTIFACT_DOWNLOAD_TTL": 1200,
                "CONNECTIVITY_CHECK_DEFAULT": False,
            },
        )
        assert response.status_code == status.HTTP_200_OK
        expected_keys = 3
        assert len(response.json()) == expected_keys

        list_payload = api_admin_client.get("/api/sep/admin/settings/").json()
        sync = _find_setting(
            list_payload, SettingClassEnum.SEP_SETTINGS.value, "SYNC_REFRESH_TIME"
        )
        ttl = _find_setting(
            list_payload, SettingClassEnum.SEP_SETTINGS.value, "ARTIFACT_DOWNLOAD_TTL"
        )
        check = _find_setting(
            list_payload,
            SettingClassEnum.SEP_SETTINGS.value,
            "CONNECTIVITY_CHECK_DEFAULT",
        )
        expected_ttl = 1200
        expected_sync = 12
        assert sync["value"] == expected_sync
        assert ttl["value"] == expected_ttl
        assert check["value"] is False

    async def test_partial_failure_rolls_back(
        self,
        api_admin_client: TestClient,
        override_session: AsyncSession,
    ) -> None:
        """A single invalid key rejects the whole batch — zero rows are written."""
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SYNC_REFRESH_TIME": 10, "ARTIFACT_DOWNLOAD_TTL": "not-a-number"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        rows = await SettingsOverrideManager.list(
            override_session, setting_class=SettingClassEnum.SEP_SETTINGS
        )
        assert rows == []

    async def test_inline_refresh_reflects_in_proxy(
        self, api_admin_client: TestClient
    ) -> None:
        """After PATCH, the proxy returns the new value without the background refresher."""
        original = sep_settings.SYNC_REFRESH_TIME
        api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SYNC_REFRESH_TIME": original + 5},
        )
        try:
            assert original + 5 == sep_settings.SYNC_REFRESH_TIME
        finally:
            sep_settings._set_snapshot({})

    async def test_unknown_key_returns_422(self, api_admin_client: TestClient) -> None:
        """An unknown key is rejected with ``type='unknown_key'`` in the per-key error."""
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"NONEXISTENT": 1},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()["detail"]
        assert any(entry["type"] == "unknown_key" for entry in detail)

    async def test_not_overridable_field_returns_422(
        self, api_admin_client: TestClient
    ) -> None:
        """Patching a NOT_OVERRIDABLE field returns 422 with ``type='not_overridable'``."""
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"INVENTORY_ENDPOINT": "https://attacker.example"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()["detail"]
        assert any(
            entry["type"] == ReloadClassification.NOT_OVERRIDABLE.value
            for entry in detail
        )

    async def test_constraint_violation_returns_422(
        self, api_admin_client: TestClient
    ) -> None:
        """A ``PositiveInt`` violation surfaces the Pydantic constraint error."""
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"ARTIFACT_DOWNLOAD_TTL": -1},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_mixed_failure_modes_aggregate_in_detail(
        self,
        api_admin_client: TestClient,
        override_session: AsyncSession,
    ) -> None:
        """Three error types in one batch produce three matching ``detail`` entries."""
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={
                "SYNC_REFRESH_TIME": 10,
                "BOGUS_KEY": 1,
                "INVENTORY_ENDPOINT": "https://example.com",
                "ARTIFACT_DOWNLOAD_TTL": -1,
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        types = {entry["type"] for entry in response.json()["detail"]}
        assert "unknown_key" in types
        assert ReloadClassification.NOT_OVERRIDABLE.value in types
        assert any("greater_than" in t for t in types)

        rows = await SettingsOverrideManager.list(
            override_session, setting_class=SettingClassEnum.SEP_SETTINGS
        )
        assert rows == []

    async def test_empty_body_returns_422(self, api_admin_client: TestClient) -> None:
        """An empty PATCH body fails the ``min_length=1`` root model constraint."""
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings", json={}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_integrity_error_triggers_single_retry(
        self,
        api_admin_client: TestClient,
        override_session: AsyncSession,
    ) -> None:
        """A concurrent-PATCH IntegrityError causes one rollback + replay; the row lands."""
        new_value = 17
        original = settings_routes._stage_and_commit_overrides
        raised = False

        async def flaky(**kwargs: Any) -> None:
            nonlocal raised
            if not raised:
                raised = True
                raise IntegrityError("statement", "params", Exception("dup"))
            await original(**kwargs)

        with patch.object(
            settings_routes, "_stage_and_commit_overrides", side_effect=flaky
        ) as spy:
            response = api_admin_client.patch(
                "/api/sep/admin/settings/SEPSettings",
                json={"SYNC_REFRESH_TIME": new_value},
            )
        assert response.status_code == status.HTTP_200_OK

        expected_call_count = 2
        assert spy.call_count == expected_call_count

        rows = await SettingsOverrideManager.list(
            override_session, setting_class=SettingClassEnum.SEP_SETTINGS
        )
        assert len(rows) == 1
        assert rows[0].value == new_value
        assert rows[0].is_active is True


@pytest.mark.asyncio
class TestSepSettingsDelete:
    """Tests for ``DELETE /api/sep/admin/settings/{setting_class}/{key}``."""

    async def test_delete_existing_override(
        self,
        api_admin_client: TestClient,
        override_session: AsyncSession,
    ) -> None:
        """Deleting an override row succeeds with 204 and clears ``has_override``."""
        api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SYNC_REFRESH_TIME": 11},
        )
        response = api_admin_client.delete(
            "/api/sep/admin/settings/SEPSettings/SYNC_REFRESH_TIME"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        rows = await SettingsOverrideManager.list(
            override_session, setting_class=SettingClassEnum.SEP_SETTINGS
        )
        assert rows == []

    async def test_delete_idempotent_when_no_row(
        self, api_admin_client: TestClient
    ) -> None:
        """Deleting a HOT field with no override row still returns 204."""
        response = api_admin_client.delete(
            "/api/sep/admin/settings/SEPSettings/SYNC_REFRESH_TIME"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_delete_not_overridable_returns_409(
        self, api_admin_client: TestClient
    ) -> None:
        """Deleting a NOT_OVERRIDABLE field returns 409 — the row can't exist."""
        response = api_admin_client.delete(
            "/api/sep/admin/settings/SEPSettings/INVENTORY_ENDPOINT"
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_delete_unknown_key_returns_404(
        self, api_admin_client: TestClient
    ) -> None:
        """Deleting an unknown key returns 404."""
        response = api_admin_client.delete(
            "/api/sep/admin/settings/SEPSettings/DOES_NOT_EXIST"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
class TestSepSettingsNestedOverrides:
    """Tests for ``__``-delimited nested overrides on ``SEPSettings.SESSION``."""

    @pytest.fixture(autouse=True)
    def _reset_proxy_snapshot(self) -> Iterator[None]:
        """Clear the global proxy snapshot after each nested test."""
        yield
        sep_settings._set_snapshot({})

    async def test_patch_nested_override_persists_and_marks_parent(
        self, api_admin_client: TestClient
    ) -> None:
        """A nested PATCH persists, echoes the nested key, and marks the parent."""
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SESSION__SAMESITE": "strict"},
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body[0]["key"] == "SESSION__SAMESITE"
        assert body[0]["value"] == "strict"
        assert body[0]["has_override"] is True
        # The parent reads back as having an override.
        parent = api_admin_client.get("/api/sep/admin/settings/SEPSettings/SESSION")
        assert parent.json()["has_override"] is True
        # The nested leaf reads back its current value.
        leaf = api_admin_client.get(
            "/api/sep/admin/settings/SEPSettings/SESSION__SAMESITE"
        )
        assert leaf.json()["value"] == "strict"

    async def test_patch_nested_coerces_int_to_timedelta(
        self, api_admin_client: TestClient
    ) -> None:
        """``SESSION__MAX_AGE`` accepts a JSON int and coerces it to a timedelta."""
        override_seconds = 7200
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SESSION__MAX_AGE": override_seconds},
        )
        assert response.status_code == status.HTTP_200_OK
        assert sep_settings.SESSION.MAX_AGE.total_seconds() == override_seconds

    async def test_patch_nested_rejects_unknown_nested_field(
        self, api_admin_client: TestClient
    ) -> None:
        """An unknown nested leaf is rejected with ``unknown_nested_field``."""
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SESSION__BOGUS": 1},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()["detail"]
        assert any(entry["type"] == "unknown_nested_field" for entry in detail)

    async def test_patch_nested_rejects_not_overridable_parent(
        self, api_admin_client: TestClient
    ) -> None:
        """A nested key under a non-overridable parent is rejected as not_overridable."""
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"INVENTORY_ENDPOINT__SCHEME": "http"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()["detail"]
        assert any(entry["type"] == "not_overridable" for entry in detail)

    async def test_patch_whole_parent_rejected_for_nested_only(
        self, api_admin_client: TestClient
    ) -> None:
        """Replacing the whole NESTED_ONLY parent object is rejected."""
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SESSION": {"MAX_AGE": 3600}},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()["detail"]
        assert any(
            entry["type"] == "not_overridable" and entry["loc"] == ["body", "SESSION"]
            for entry in detail
        )

    async def test_delete_whole_parent_rejected_for_nested_only(
        self, api_admin_client: TestClient
    ) -> None:
        """DELETE on the whole NESTED_ONLY parent returns 422 (not 404)."""
        response = api_admin_client.delete(
            "/api/sep/admin/settings/SEPSettings/SESSION"
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        detail = response.json()["detail"]
        assert any(entry["type"] == "not_overridable" for entry in detail)

    async def test_get_whole_parent_returns_merged_value(
        self, api_admin_client: TestClient
    ) -> None:
        """GET on the whole parent is allowed and returns the merged value."""
        api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SESSION__SAMESITE": "strict"},
        )
        response = api_admin_client.get("/api/sep/admin/settings/SEPSettings/SESSION")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["value"]["SAMESITE"] == "strict"

    async def test_delete_nested_override_clears_merged_value(
        self, api_admin_client: TestClient
    ) -> None:
        """Deleting a nested override reverts the leaf to its YAML/env value (AC #3)."""
        override_seconds = 7200
        original = sep_settings.SESSION.MAX_AGE
        api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SESSION__MAX_AGE": override_seconds},
        )
        assert sep_settings.SESSION.MAX_AGE.total_seconds() == override_seconds
        response = api_admin_client.delete(
            "/api/sep/admin/settings/SEPSettings/SESSION__MAX_AGE"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert original == sep_settings.SESSION.MAX_AGE

    async def test_delete_nested_override_idempotent_when_absent(
        self, api_admin_client: TestClient
    ) -> None:
        """Deleting a never-set nested override still returns 204."""
        response = api_admin_client.delete(
            "/api/sep/admin/settings/SEPSettings/SESSION__MAX_AGE"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_list_marks_parent_overridden_when_only_nested_rows_exist(
        self, api_admin_client: TestClient
    ) -> None:
        """The LIST ``has_override`` flag mirrors the runtime nested-row filter."""
        api_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SESSION__SAMESITE": "strict"},
        )
        list_payload = api_admin_client.get("/api/sep/admin/settings/").json()
        session_entry = _find_setting(
            list_payload, SettingClassEnum.SEP_SETTINGS.value, "SESSION"
        )
        assert session_entry["has_override"] is True


@pytest.mark.asyncio
class TestSepSettingsAuth:
    """Authentication / authorisation tests for the settings router."""

    async def test_unauthenticated_get_returns_401(
        self, api_unauthenticated_client: TestClient
    ) -> None:
        """An unauthenticated GET responds with a JSON 401."""
        response = api_unauthenticated_client.get(
            "/api/sep/admin/settings/", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")

    async def test_non_admin_get_returns_403(
        self, api_non_admin_client: TestClient
    ) -> None:
        """A non-admin user is rejected with 403 on every endpoint."""
        response = api_non_admin_client.get("/api/sep/admin/settings/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_non_admin_patch_returns_403(
        self, api_non_admin_client: TestClient
    ) -> None:
        """A non-admin user cannot mutate settings."""
        response = api_non_admin_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SYNC_REFRESH_TIME": 10},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_cookie_admin_patch_without_bearer_returns_401(
        self, api_admin_cookie_client: TestClient
    ) -> None:
        """Cookie-authenticated admin cannot PATCH without a Bearer header (CSRF defense)."""
        response = api_admin_cookie_client.patch(
            "/api/sep/admin/settings/SEPSettings",
            json={"SYNC_REFRESH_TIME": 10},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_cookie_admin_delete_without_bearer_returns_401(
        self, api_admin_cookie_client: TestClient
    ) -> None:
        """Cookie-authenticated admin cannot DELETE without a Bearer header (CSRF defense)."""
        response = api_admin_cookie_client.delete(
            "/api/sep/admin/settings/SEPSettings/SYNC_REFRESH_TIME"
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_cookie_admin_can_still_read(
        self, api_admin_cookie_client: TestClient
    ) -> None:
        """GET endpoints remain accessible via cookie auth — only mutations require Bearer."""
        response = api_admin_cookie_client.get("/api/sep/admin/settings/")
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
class TestSepSettingsSecondaryClasses:
    """Smoke tests for the Snippets and Messages classes wired alongside SEP."""

    async def test_patch_snippets_setting(self, api_admin_client: TestClient) -> None:
        """A Snippets HOT field is patchable via the SEP router."""
        original = snippets_settings.ENABLE_MANUAL_SYNC
        response = api_admin_client.patch(
            "/api/sep/admin/settings/SnippetsSettings",
            json={"ENABLE_MANUAL_SYNC": not original},
        )
        try:
            assert response.status_code == status.HTTP_200_OK
            assert snippets_settings.ENABLE_MANUAL_SYNC is (not original)
        finally:
            snippets_settings._set_snapshot({})

    async def test_patch_messages_setting(self, api_admin_client: TestClient) -> None:
        """A Messages HOT field is patchable via the SEP router."""
        target_level = 30
        response = api_admin_client.patch(
            "/api/sep/admin/settings/MessagesSettings",
            json={"LEVEL": target_level},
        )
        try:
            assert response.status_code == status.HTTP_200_OK
            assert target_level == messages_settings.LEVEL
        finally:
            messages_settings._set_snapshot({})
