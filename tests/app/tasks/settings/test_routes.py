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

"""Tests for the Tasks settings REST API at ``/admin/settings/`` (mounted at ``/api/tasks``)."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient

from app.api.deps import get_current_user
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.registry import ReloadClassification
from app.models import CasdoorUser
from app.tasks.config import tasks_settings
from app.tasks.deps import get_executor, get_session
from app.tasks.main import tasks_app


@pytest.fixture(name="admin_test_client")
def admin_test_client_fixture(
    admin_user: CasdoorUser,
    session: AsyncSession,
    mock_executor: AsyncMock,
) -> Iterator[TestClient]:
    """Yield an admin-authenticated Tasks TestClient bound to the test session."""
    tasks_app.dependency_overrides[get_current_user] = lambda: admin_user
    tasks_app.dependency_overrides[get_session] = lambda: session
    tasks_app.dependency_overrides[get_executor] = lambda: mock_executor
    yield TestClient(tasks_app)
    tasks_app.dependency_overrides = {}


@pytest.fixture(name="non_admin_client")
def non_admin_client_fixture(
    regular_user: CasdoorUser,
    session: AsyncSession,
    mock_executor: AsyncMock,
) -> Iterator[TestClient]:
    """Yield a non-admin Tasks TestClient bound to the test session."""
    tasks_app.dependency_overrides[get_current_user] = lambda: regular_user
    tasks_app.dependency_overrides[get_session] = lambda: session
    tasks_app.dependency_overrides[get_executor] = lambda: mock_executor
    yield TestClient(tasks_app)
    tasks_app.dependency_overrides = {}


@pytest.fixture(name="unauthenticated_client")
def unauthenticated_client_fixture(
    session: AsyncSession,
    mock_executor: AsyncMock,
) -> Iterator[TestClient]:
    """Yield an unauthenticated Tasks TestClient bound to the test session."""
    tasks_app.dependency_overrides = {}
    tasks_app.dependency_overrides[get_session] = lambda: session
    tasks_app.dependency_overrides[get_executor] = lambda: mock_executor
    yield TestClient(tasks_app)
    tasks_app.dependency_overrides = {}


@pytest.mark.asyncio
class TestTasksSettingsApi:
    """Cover the Tasks sub-app settings router end-to-end."""

    async def test_list_returns_tasks_class(
        self, admin_test_client: TestClient
    ) -> None:
        """The Tasks router exposes exactly one settings class: TasksSettings."""
        response = admin_test_client.get("/admin/settings/")
        assert response.status_code == status.HTTP_200_OK
        groups = response.json()["groups"]
        assert len(groups) == 1
        assert groups[0]["setting_class"] == SettingClassEnum.TASKS_SETTINGS.value

    async def test_get_single_setting(self, admin_test_client: TestClient) -> None:
        """A single Tasks HOT field returns its metadata."""
        response = admin_test_client.get(
            "/admin/settings/TasksSettings/STALENESS_THRESHOLD_SECONDS"
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["key"] == "STALENESS_THRESHOLD_SECONDS"
        assert body["reload"] == ReloadClassification.HOT.value

    async def test_patch_hot_field(
        self,
        admin_test_client: TestClient,
        session: AsyncSession,
    ) -> None:
        """PATCHing a Tasks HOT field creates a row in the Tasks DB."""
        new_value = 7200
        response = admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"STALENESS_THRESHOLD_SECONDS": new_value},
        )
        assert response.status_code == status.HTTP_200_OK
        rows = await SettingsOverrideManager.list(
            session, setting_class=SettingClassEnum.TASKS_SETTINGS
        )
        assert len(rows) == 1
        assert rows[0].value == new_value

    async def test_patch_multiple_atomic(
        self,
        admin_test_client: TestClient,
        session: AsyncSession,
    ) -> None:
        """Two HOT Tasks fields persist in a single transaction."""
        response = admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={
                "STALENESS_THRESHOLD_SECONDS": 1800,
                "PRE_EXECUTION_CONNECTIVITY_CHECK": "block",
            },
        )
        assert response.status_code == status.HTTP_200_OK
        rows = await SettingsOverrideManager.list(
            session, setting_class=SettingClassEnum.TASKS_SETTINGS
        )
        expected_rows = 2
        assert len(rows) == expected_rows

    async def test_patch_inline_refresh(self, admin_test_client: TestClient) -> None:
        """After PATCH, the proxy returns the new value without the background refresher."""
        new_value = 99
        response = admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"STALENESS_THRESHOLD_SECONDS": new_value},
        )
        try:
            assert response.status_code == status.HTTP_200_OK
            assert new_value == tasks_settings.STALENESS_THRESHOLD_SECONDS
        finally:
            tasks_settings._set_snapshot({})

    async def test_patch_partial_failure_rolls_back(
        self,
        admin_test_client: TestClient,
        session: AsyncSession,
    ) -> None:
        """One bad key rejects the batch and writes zero rows."""
        response = admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={
                "STALENESS_THRESHOLD_SECONDS": 1800,
                "PRE_EXECUTION_CONNECTIVITY_CHECK": "not-a-valid-mode",
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        rows = await SettingsOverrideManager.list(
            session, setting_class=SettingClassEnum.TASKS_SETTINGS
        )
        assert rows == []

    async def test_patch_not_overridable_field(
        self, admin_test_client: TestClient
    ) -> None:
        """A non-HOT Tasks field is rejected as ``not_overridable``."""
        response = admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"UVICORN_PORT": 9999},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        types = {entry["type"] for entry in response.json()["detail"]}
        assert ReloadClassification.NOT_OVERRIDABLE.value in types

    async def test_patch_type_mismatch(self, admin_test_client: TestClient) -> None:
        """An int field rejects a string value with a structured 422."""
        response = admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"STALENESS_THRESHOLD_SECONDS": "not-a-number"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_delete_idempotent(self, admin_test_client: TestClient) -> None:
        """Deleting a HOT field with no row still succeeds with 204."""
        response = admin_test_client.delete(
            "/admin/settings/TasksSettings/STALENESS_THRESHOLD_SECONDS"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    async def test_unauthenticated_returns_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        """An unauthenticated request to the settings endpoint returns 401."""
        response = unauthenticated_client.get("/admin/settings/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_non_admin_returns_403(self, non_admin_client: TestClient) -> None:
        """A non-admin user is rejected with 403."""
        response = non_admin_client.get("/admin/settings/")
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
class TestTasksSettingsNestedOverrides:
    """Cover ``__``-delimited nested overrides on ``TasksSettings`` parents."""

    @pytest.fixture(autouse=True)
    def _reset_proxy_snapshot(self) -> Iterator[None]:
        """Clear the global proxy snapshot after each nested test."""
        yield
        tasks_settings._set_snapshot({})

    async def test_patch_nested_nomad_timeout(
        self, admin_test_client: TestClient
    ) -> None:
        """A nested ``NOMAD__TIMEOUT`` override persists and reflects in the proxy."""
        override_timeout = 30
        response = admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"NOMAD__TIMEOUT": override_timeout},
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        # The response echoes the canonical (case-corrected) key.
        assert body[0]["key"] == "NOMAD__timeout"
        assert body[0]["value"] == override_timeout
        assert tasks_settings.NOMAD.timeout == override_timeout

    async def test_patch_nested_security_header_bool(
        self, admin_test_client: TestClient
    ) -> None:
        """A nested case-insensitive boolean leaf override applies."""
        response = admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"SECURITY_HEADERS__X_FRAME_OPTIONS_DENY": False},
        )
        assert response.status_code == status.HTTP_200_OK
        assert tasks_settings.SECURITY_HEADERS.x_frame_options_deny is False

    async def test_patch_multi_level_security_header(
        self, admin_test_client: TestClient
    ) -> None:
        """A multi-level override instantiates the nested intermediate model."""
        max_age = 31536000
        response = admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"SECURITY_HEADERS__STRICT_TRANSPORT_SECURITY__MAX_AGE": max_age},
        )
        assert response.status_code == status.HTTP_200_OK
        sts = tasks_settings.SECURITY_HEADERS.strict_transport_security
        assert sts is not None
        assert sts.max_age == max_age

    async def test_patch_whole_parent_nomad_rejected(
        self, admin_test_client: TestClient
    ) -> None:
        """Replacing the whole NESTED_ONLY ``NOMAD`` parent is rejected."""
        response = admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"NOMAD": {"timeout": 30}},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        types = {entry["type"] for entry in response.json()["detail"]}
        assert "not_overridable" in types

    async def test_delete_nested_nomad_timeout(
        self,
        admin_test_client: TestClient,
        session: AsyncSession,
    ) -> None:
        """Deleting a nested override removes its row and returns 204."""
        admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"NOMAD__TIMEOUT": 30},
        )
        response = admin_test_client.delete(
            "/admin/settings/TasksSettings/NOMAD__TIMEOUT"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        rows = await SettingsOverrideManager.list(
            session, setting_class=SettingClassEnum.TASKS_SETTINGS
        )
        assert rows == []

    async def test_delete_whole_parent_nomad_rejected(
        self, admin_test_client: TestClient
    ) -> None:
        """DELETE on the whole NESTED_ONLY ``NOMAD`` parent returns 422."""
        response = admin_test_client.delete("/admin/settings/TasksSettings/NOMAD")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        types = {entry["type"] for entry in response.json()["detail"]}
        assert "not_overridable" in types

    async def test_list_marks_security_headers_overridden(
        self, admin_test_client: TestClient
    ) -> None:
        """A nested-only override marks the parent ``has_override`` in LIST."""
        admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"SECURITY_HEADERS__X_FRAME_OPTIONS_DENY": False},
        )
        groups = admin_test_client.get("/admin/settings/").json()["groups"]
        settings = groups[0]["settings"]
        security_headers = next(s for s in settings if s["key"] == "SECURITY_HEADERS")
        assert security_headers["has_override"] is True

    async def test_get_multi_level_nested_before_override_returns_200(
        self, admin_test_client: TestClient
    ) -> None:
        """GET on a multi-level key whose intermediate is ``None`` returns 200, not 500."""
        # ``STRICT_TRANSPORT_SECURITY`` defaults to ``None``; reading a leaf
        # under it must not raise.
        response = admin_test_client.get(
            "/admin/settings/TasksSettings"
            "/SECURITY_HEADERS__STRICT_TRANSPORT_SECURITY__MAX_AGE"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["value"] is None

    async def test_case_insensitive_keys_collapse_to_one_row(
        self,
        admin_test_client: TestClient,
        session: AsyncSession,
    ) -> None:
        """Mixed-case spellings of the same nested key map to a single override row."""
        admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"security_headers__x_frame_options_deny": False},
        )
        # An uppercase DELETE removes the row created by the lowercase PATCH.
        response = admin_test_client.delete(
            "/admin/settings/TasksSettings/SECURITY_HEADERS__X_FRAME_OPTIONS_DENY"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        rows = await SettingsOverrideManager.list(
            session, setting_class=SettingClassEnum.TASKS_SETTINGS
        )
        assert rows == []
