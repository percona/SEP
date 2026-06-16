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

"""Tests for the SEP config export YAML API route at ``/api/sep/admin/config/export``."""

from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import yaml
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.exceptions import HTTPBadGatewayException
from app.core.requests import RemoteAPI
from app.core.settings_override.models import SettingClassEnum
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

EXPORT_URL = "/api/sep/admin/config/export"
SETTINGS_LIST_URL = "/api/sep/admin/settings/"
REDACTED_SECRET = "**********"
SAMPLE_STALENESS_THRESHOLD_SECONDS = 3600

SAMPLE_TASKS_LIST: dict[str, Any] = {
    "groups": [
        {
            "setting_class": SettingClassEnum.TASKS_SETTINGS.value,
            "settings": [
                {
                    "setting_class": SettingClassEnum.TASKS_SETTINGS.value,
                    "key": "STALENESS_THRESHOLD_SECONDS",
                    "key_path": ["STALENESS_THRESHOLD_SECONDS"],
                    "value": SAMPLE_STALENESS_THRESHOLD_SECONDS,
                    "default_value": SAMPLE_STALENESS_THRESHOLD_SECONDS,
                    "type": "int",
                    "reload": "hot",
                    "description": None,
                    "is_secret": False,
                    "is_complex": False,
                    "has_override": False,
                },
                {
                    "setting_class": SettingClassEnum.TASKS_SETTINGS.value,
                    "key": "API_SECRET",
                    "key_path": ["API_SECRET"],
                    "value": REDACTED_SECRET,
                    "default_value": None,
                    "type": "SecretStr",
                    "reload": "hot",
                    "description": None,
                    "is_secret": True,
                    "is_complex": False,
                    "has_override": False,
                },
            ],
        }
    ]
}


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


@pytest.fixture(name="mock_tasks_api")
def mock_tasks_api_fixture() -> Iterator[AsyncMock]:
    """Mock the TaskAPI dependency used by the export fan-out."""
    mock = AsyncMock(spec=RemoteAPI)
    mock.get.return_value = SAMPLE_TASKS_LIST
    return mock


@pytest.fixture(name="api_admin_client")
def api_admin_client_fixture(
    admin_user: CasdoorUser,
    override_session: AsyncSession,
    mock_tasks_api: AsyncMock,
) -> Iterator[TestClient]:
    """Yield an admin-authenticated SEP TestClient with the in-memory SEP session."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock_tasks_api
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture(name="api_non_admin_client")
def api_non_admin_client_fixture(
    regular_user: CasdoorUser,
    override_session: AsyncSession,
    mock_tasks_api: AsyncMock,
) -> Iterator[TestClient]:
    """Yield a non-admin SEP TestClient with the in-memory SEP session."""
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock_tasks_api
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture(name="api_unauthenticated_client")
def api_unauthenticated_client_fixture(
    override_session: AsyncSession,
) -> Iterator[TestClient]:
    """Yield an unauthenticated SEP TestClient — export calls should 401."""
    sep_app.dependency_overrides = {}
    sep_app.dependency_overrides[get_session] = lambda: override_session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


def _list_keys_by_class(client: TestClient) -> dict[str, set[str]]:
    """Locate LIST keys grouped by settings class in the admin settings payload."""
    response = client.get(SETTINGS_LIST_URL)
    assert response.status_code == status.HTTP_200_OK
    grouped: dict[str, set[str]] = {}
    for group in response.json()["groups"]:
        grouped[group["setting_class"]] = {entry["key"] for entry in group["settings"]}
    return grouped


def _secret_fields_from_list(client: TestClient) -> list[tuple[str, str, Any]]:
    """Locate every ``is_secret`` LIST entry as ``(class, key, value)`` tuples."""
    response = client.get(SETTINGS_LIST_URL)
    assert response.status_code == status.HTTP_200_OK
    secrets: list[tuple[str, str, Any]] = []
    for group in response.json()["groups"]:
        secrets.extend(
            (group["setting_class"], entry["key"], entry["value"])
            for entry in group["settings"]
            if entry.get("is_secret")
        )
    return secrets


@pytest.mark.asyncio
class TestSepConfigExportAuth:
    """Authentication / authorisation tests for the config export router."""

    async def test_unauthenticated_get_returns_401(
        self, api_unauthenticated_client: TestClient
    ) -> None:
        """An unauthenticated GET responds with a JSON 401."""
        response = api_unauthenticated_client.get(EXPORT_URL, follow_redirects=False)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")

    async def test_non_admin_get_returns_403(
        self, api_non_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """A non-admin user is rejected with 403 before the Tasks fan-out runs."""
        response = api_non_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_tasks_api.get.assert_not_called()


@pytest.mark.asyncio
class TestSepConfigExportYaml:
    """Tests for ``GET /api/sep/admin/config/export`` happy-path YAML rendering."""

    async def test_returns_yaml_attachment(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Returns YAML with download headers and one top-level key per wired class."""
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"].startswith("application/x-yaml")
        assert response.headers["content-disposition"].startswith("attachment;")
        assert 'filename="sep-config-' in response.headers["content-disposition"]
        assert response.headers["content-disposition"].endswith('.yaml"')

        payload = yaml.safe_load(response.text)
        assert set(payload) == {
            SettingClassEnum.SEP_SETTINGS.value,
            SettingClassEnum.SNIPPETS_SETTINGS.value,
            SettingClassEnum.MESSAGES_SETTINGS.value,
            SettingClassEnum.TASKS_SETTINGS.value,
        }
        mock_tasks_api.get.assert_awaited_once_with("/admin/settings/")

    async def test_export_keys_match_list_for_sep_classes(
        self, api_admin_client: TestClient
    ) -> None:
        """Each SEP-wired class block exposes the same keys as ``GET /settings/``."""
        export = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
        list_keys = _list_keys_by_class(api_admin_client)
        for setting_class in (
            SettingClassEnum.SEP_SETTINGS.value,
            SettingClassEnum.SNIPPETS_SETTINGS.value,
            SettingClassEnum.MESSAGES_SETTINGS.value,
        ):
            assert set(export[setting_class]) == list_keys[setting_class]

    async def test_secret_fields_match_list_projection(
        self, api_admin_client: TestClient
    ) -> None:
        """Every ``is_secret`` LIST entry dumps to the same value in the export."""
        export = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
        secrets = _secret_fields_from_list(api_admin_client)
        assert secrets, "expected at least one secret field on LIST for this assertion"
        for setting_class, key, list_value in secrets:
            assert export[setting_class][key] == list_value

    async def test_secretstr_literals_redacted_in_yaml(
        self, api_admin_client: TestClient, mocker
    ) -> None:
        """Scalar and nested ``SecretStr`` values render as ``**********``."""
        from pydantic import SecretStr

        from app.core.config import PMMSettings
        from app.core.utils.fields import UniqueList
        from app.sep.config import (
            HealthReportSettings,
            sep_settings,
            SyncerExtraKwargs,
            SyncOptions,
        )

        mocker.patch.object(
            sep_settings,
            "HEALTH_REPORT",
            HealthReportSettings(
                upload=True,
                endpoint="https://snow.example.com",
                api_key=SecretStr("local-secret"),
                client_id="client-1",
            ),
        )
        mocker.patch.object(
            sep_settings,
            "SYNCER_EXTRA_KWARGS",
            SyncerExtraKwargs(
                pmm=PMMSettings(api_key=SecretStr("syncer-extra-secret"))
            ),
        )
        mocker.patch.object(
            sep_settings,
            "SYNCERS",
            UniqueList(
                [
                    SyncOptions(
                        syncer="PMMSyncer",
                        pmm=PMMSettings(api_key=SecretStr("syncer-inline-secret")),
                    )
                ]
            ),
        )
        yaml_text = api_admin_client.get(EXPORT_URL).text
        export = yaml.safe_load(yaml_text)
        sep_block = export[SettingClassEnum.SEP_SETTINGS.value]
        assert sep_block["HEALTH_REPORT"]["api_key"] == REDACTED_SECRET
        assert (
            export[SettingClassEnum.TASKS_SETTINGS.value]["API_SECRET"]
            == REDACTED_SECRET
        )
        assert sep_block["SYNCER_EXTRA_KWARGS"]["pmm"]["api_key"] == REDACTED_SECRET
        assert sep_block["SYNCERS"][0]["pmm"]["api_key"] == REDACTED_SECRET
        assert "syncer-extra-secret" not in yaml_text
        assert "syncer-inline-secret" not in yaml_text

    async def test_complex_field_renders_as_mapping(
        self, api_admin_client: TestClient
    ) -> None:
        """``SEPSettings.PLUGINS`` is emitted as a structured value, not a repr blob."""
        export = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
        plugins = export[SettingClassEnum.SEP_SETTINGS.value]["PLUGINS"]
        assert isinstance(plugins, list)
        if plugins:
            assert isinstance(plugins[0], dict)


@pytest.mark.asyncio
class TestSepConfigExportTasksFanOut:
    """Tests for Tasks fan-out success and upstream failure on config export."""

    async def test_tasks_settings_merged_from_fan_out(
        self, api_admin_client: TestClient
    ) -> None:
        """Tasks LIST values appear under the ``TasksSettings`` top-level key."""
        export = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
        tasks_block = export[SettingClassEnum.TASKS_SETTINGS.value]
        assert (
            tasks_block["STALENESS_THRESHOLD_SECONDS"]
            == SAMPLE_STALENESS_THRESHOLD_SECONDS
        )
        assert tasks_block["API_SECRET"] == REDACTED_SECRET

    async def test_tasks_http_exception_returns_502(
        self,
        api_admin_client: TestClient,
        mock_tasks_api: AsyncMock,
    ) -> None:
        """Return ``502`` + ``{"detail": ...}`` when the Tasks API raises ``HTTPException``."""
        mock_tasks_api.get.side_effect = HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="tasks unavailable",
        )
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {"detail": "tasks unavailable"}

    async def test_tasks_oserror_returns_502(
        self,
        api_admin_client: TestClient,
        mock_tasks_api: AsyncMock,
    ) -> None:
        """Return ``502`` + ``{"detail": ...}`` when the Tasks API raises an ``OSError``."""
        mock_tasks_api.get.side_effect = OSError("connection refused")
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json() == {"detail": "connection refused"}

    async def test_tasks_bad_gateway_exception_returns_502(
        self,
        api_admin_client: TestClient,
        mock_tasks_api: AsyncMock,
    ) -> None:
        """Return ``502`` + ``{"detail": ...}`` when the Tasks client raises ``HTTPBadGatewayException``."""
        mock_tasks_api.get.side_effect = HTTPBadGatewayException("tasks unreachable")
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json() == {"detail": "tasks unreachable"}

    async def test_tasks_missing_groups_returns_502(
        self,
        api_admin_client: TestClient,
        mock_tasks_api: AsyncMock,
    ) -> None:
        """Return ``502`` + ``{"detail": ...}`` when Tasks LIST payload lacks ``groups``."""
        mock_tasks_api.get.return_value = {"unexpected": True}
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "groups" in response.json()["detail"]

    async def test_tasks_missing_tasks_settings_group_returns_502(
        self,
        api_admin_client: TestClient,
        mock_tasks_api: AsyncMock,
    ) -> None:
        """Return ``502`` when Tasks LIST has ``groups`` but no ``TasksSettings`` entry."""
        mock_tasks_api.get.return_value = {"groups": []}
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert SettingClassEnum.TASKS_SETTINGS.value in response.json()["detail"]

    async def test_tasks_setting_entry_missing_value_returns_502(
        self,
        api_admin_client: TestClient,
        mock_tasks_api: AsyncMock,
    ) -> None:
        """Return ``502`` when a Tasks LIST setting entry omits ``value``."""
        mock_tasks_api.get.return_value = {
            "groups": [
                {
                    "setting_class": SettingClassEnum.TASKS_SETTINGS.value,
                    "settings": [{"key": "STALENESS_THRESHOLD_SECONDS"}],
                }
            ]
        }
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "value" in response.json()["detail"]
