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
from app.core.settings_override.cache import build_snapshot
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.registry import ReloadClassification
from app.models import CasdoorUser
from app.tasks.config import tasks_settings, TasksSettings
from app.tasks.deps import get_request_executor, get_session
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
    tasks_app.dependency_overrides[get_request_executor] = lambda: mock_executor
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
    tasks_app.dependency_overrides[get_request_executor] = lambda: mock_executor
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
    tasks_app.dependency_overrides[get_request_executor] = lambda: mock_executor
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

    async def test_patch_materializer_field_nomad_is_patchable(
        self,
        admin_test_client: TestClient,
        session: AsyncSession,
    ) -> None:
        """A ``NOMAD`` override is accepted and stored as raw config JSON.

        Regression: ``NOMAD`` declares a fingerprint materializer; the PATCH
        validation must route through it and persist the raw config dict (not the
        coerced ``NomadExecutor`` instance) so the snapshot loader materializes a
        diff-stable fingerprint.
        """
        raw_config = {"endpoint": "https://nomad-override.example.org"}
        response = admin_test_client.patch(
            "/admin/settings/TasksSettings",
            json={"NOMAD": raw_config},
        )
        assert response.status_code == status.HTTP_200_OK
        rows = await SettingsOverrideManager.list(
            session, setting_class=SettingClassEnum.TASKS_SETTINGS, key="NOMAD"
        )
        assert len(rows) == 1
        assert rows[0].value == raw_config

        snapshot = await build_snapshot(session, TasksSettings)
        assert isinstance(snapshot["NOMAD"], dict)
        assert snapshot["NOMAD"]["endpoint"].rstrip("/") == raw_config["endpoint"]

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
