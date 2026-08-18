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

"""Tests for the SEP settings YAML export route at ``/api/sep/admin/settings/export``."""

from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import yaml
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.api.deps import require_admin_for_unsafe_methods
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.exceptions import HTTPBadGatewayException
from app.core.requests import RemoteAPI
from app.core.settings_override.models import SettingClassEnum
from app.core.utils import json_serializer
from app.sep.bundle_upload.plan import DeliveryPlan
from app.sep.config import DeliveryPlanInputs, sep_settings, SEPSettings
from app.sep.deps import (
    get_current_user,
    get_session,
    get_tasks_api,
    require_bearer_for_unsafe_methods,
)
from app.sep.main import sep_app

EXPORT_URL = "/api/sep/admin/settings/export"
SETTINGS_LIST_URL = "/api/sep/admin/settings/"
REDACTED_SECRET = "**********"
SAMPLE_STALENESS_THRESHOLD_SECONDS = 3600
DEFAULT_ALERT_BACKUP_RETENTION = 10

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
    try:
        async with async_session_maker() as session:
            yield session
    finally:
        await engine.dispose()


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
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[require_admin_for_unsafe_methods] = lambda: None
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
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: override_session
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[require_admin_for_unsafe_methods] = lambda: None
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


def _configure_health_report_upload(mocker) -> None:
    """Patch ``health_report_settings`` so upload is fully configured."""
    from pydantic import SecretStr

    from app.sep.apps.report.config import health_report_settings

    mocker.patch.object(health_report_settings, "upload", new=True)
    mocker.patch.object(health_report_settings, "endpoint", "https://snow.example.com")
    mocker.patch.object(health_report_settings, "api_key", SecretStr("local-secret"))
    mocker.patch.object(health_report_settings, "client_id", "client-1")


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
        """Respond with a JSON 401 to an unauthenticated GET."""
        response = api_unauthenticated_client.get(EXPORT_URL, follow_redirects=False)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")

    async def test_non_admin_get_returns_403(
        self, api_non_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Reject a non-admin user with 403 before the Tasks fan-out runs."""
        response = api_non_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_tasks_api.get.assert_not_called()


@pytest.mark.asyncio
class TestSepConfigExportYaml:
    """Tests for ``GET /api/sep/admin/settings/export`` happy-path YAML rendering."""

    async def test_returns_yaml_attachment(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Return YAML with download headers and one top-level key per wired class."""
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"].startswith("application/x-yaml")
        assert response.headers["content-disposition"].startswith("attachment;")
        assert 'filename="sep-config-' in response.headers["content-disposition"]
        assert response.headers["content-disposition"].endswith('.yaml"')

        payload = yaml.safe_load(response.text)
        assert set(payload) == FULL_EXPORT_CLASSES
        mock_tasks_api.get.assert_awaited_once_with("/admin/settings/")

    async def test_export_keys_match_list_for_sep_classes(
        self, api_admin_client: TestClient
    ) -> None:
        """Expose the same keys as ``GET /settings/`` for each SEP-wired class block."""
        export = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
        list_keys = _list_keys_by_class(api_admin_client)
        for setting_class in (
            SettingClassEnum.SEP_SETTINGS.value,
            SettingClassEnum.SNIPPETS_SETTINGS.value,
            SettingClassEnum.ALERTS_SETTINGS.value,
            SettingClassEnum.HEALTH_REPORT_SETTINGS.value,
        ):
            assert set(export[setting_class]) == list_keys[setting_class]

    async def test_alerts_settings_block_exported(
        self, api_admin_client: TestClient
    ) -> None:
        """Export the new ``AlertsSettings`` section with its three fields."""
        export = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
        list_keys = _list_keys_by_class(api_admin_client)
        block = export[SettingClassEnum.ALERTS_SETTINGS.value]
        # Exported keys mirror the LIST projection exactly (including the
        # ``BACKUP_INTERVAL__*`` flattening and inherited ``FASTAPI_ENV``).
        assert set(block) == list_keys[SettingClassEnum.ALERTS_SETTINGS.value]
        assert block["BACKUP_RETENTION"] == DEFAULT_ALERT_BACKUP_RETENTION
        assert block["ALERT_FOLDER_NAME"] == "SEP Alerts"

    async def test_health_report_settings_block_exported(
        self, api_admin_client: TestClient
    ) -> None:
        """Export the ``HealthReportSettings`` section with its fields."""
        export = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
        list_keys = _list_keys_by_class(api_admin_client)
        block = export[SettingClassEnum.HEALTH_REPORT_SETTINGS.value]
        assert set(block) == list_keys[SettingClassEnum.HEALTH_REPORT_SETTINGS.value]
        assert block["upload"] is False

    async def test_secret_fields_match_list_projection(
        self, api_admin_client: TestClient
    ) -> None:
        """Dump every ``is_secret`` LIST entry to the same value in the export."""
        export = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
        secrets = _secret_fields_from_list(api_admin_client)
        assert secrets, "expected at least one secret field on LIST for this assertion"
        for setting_class, key, list_value in secrets:
            assert export[setting_class][key] == list_value

    async def test_secretstr_literals_redacted_in_yaml(
        self, api_admin_client: TestClient, mocker
    ) -> None:
        """Render scalar and nested ``SecretStr`` values as ``**********``."""
        _configure_health_report_upload(mocker)
        yaml_text = api_admin_client.get(EXPORT_URL).text
        export = yaml.safe_load(yaml_text)
        health_block = export[SettingClassEnum.HEALTH_REPORT_SETTINGS.value]
        assert health_block["api_key"] == REDACTED_SECRET
        assert (
            export[SettingClassEnum.TASKS_SETTINGS.value]["API_SECRET"]
            == REDACTED_SECRET
        )
        assert "local-secret" not in yaml_text

    async def test_delivery_plan_secrets_redacted_in_yaml(
        self, api_admin_client: TestClient, mocker
    ) -> None:
        """Render every ``DIAGNOSTICS_DELIVERY`` secret as ``**********``."""
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY",
            DeliveryPlan(
                endpoint="https://snow.example.com/",
                secrets={"api_key": "plan-secret"},
                upload={
                    "path": "attachment/upload",
                    "headers": {"x-sn-apikey": {"source": "secret", "name": "api_key"}},
                },
            ),
        )
        yaml_text = api_admin_client.get(EXPORT_URL).text
        export = yaml.safe_load(yaml_text)
        block = export[SettingClassEnum.SEP_SETTINGS.value]["DIAGNOSTICS_DELIVERY"]

        assert block["secrets"]["api_key"] == REDACTED_SECRET
        assert block["upload"]["path"] == "attachment/upload"
        assert "plan-secret" not in yaml_text

    async def test_delivery_inputs_export_redacts_and_cannot_be_re_fed(
        self, api_admin_client: TestClient, mocker
    ) -> None:
        """Redact the runtime inputs, and refuse the redacted block as configuration.

        The export is what an operator carries between deployments, so the
        masked secrets it renders must not resolve back into a plan that sends
        ``**********`` to the receiver as the credential.
        """
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY_INPUTS",
            DeliveryPlanInputs(secrets={"sn_api_key": "inputs-secret"}),
        )
        yaml_text = api_admin_client.get(EXPORT_URL).text
        export = yaml.safe_load(yaml_text)
        block = export[SettingClassEnum.SEP_SETTINGS.value][
            "DIAGNOSTICS_DELIVERY_INPUTS"
        ]

        assert block["secrets"]["sn_api_key"] == REDACTED_SECRET
        assert "inputs-secret" not in yaml_text

        with pytest.raises(ValidationError, match="sn_api_key"):
            SEPSettings(DIAGNOSTICS_DELIVERY_INPUTS=block)

    async def test_inventory_endpoint_redacted_in_yaml(
        self, api_admin_client: TestClient
    ) -> None:
        """Render ``INVENTORY_ENDPOINT`` with the password masked in YAML export."""
        from app.sep.config import sep_settings

        full_url = "http://inv-user:inv-secret@inventory.internal:8080"
        try:
            sep_settings._set_snapshot({"INVENTORY_ENDPOINT": full_url})
            yaml_text = api_admin_client.get(EXPORT_URL).text
            export = yaml.safe_load(yaml_text)
            value = export[SettingClassEnum.SEP_SETTINGS.value]["INVENTORY_ENDPOINT"]
            assert "inv-secret" not in yaml_text
            assert "****" in value
            assert "inv-user" in value
        finally:
            sep_settings._set_snapshot({})

    async def test_credential_url_export_matches_list_projection(
        self, api_admin_client: TestClient
    ) -> None:
        """Dump ``INVENTORY_ENDPOINT`` to the same redacted value as the LIST endpoint."""
        from app.sep.config import sep_settings

        full_url = "http://inv-user:inv-secret@inventory.internal:8080"
        try:
            sep_settings._set_snapshot({"INVENTORY_ENDPOINT": full_url})
            export = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
            list_response = api_admin_client.get(SETTINGS_LIST_URL).json()
            for group in list_response["groups"]:
                if group["setting_class"] != SettingClassEnum.SEP_SETTINGS.value:
                    continue
                for entry in group["settings"]:
                    if entry["key"] == "INVENTORY_ENDPOINT":
                        list_value = entry["value"]
                        break
                else:
                    raise AssertionError("INVENTORY_ENDPOINT missing from LIST")
                break
            else:
                raise AssertionError("SEP_SETTINGS group missing from LIST")
            assert (
                export[SettingClassEnum.SEP_SETTINGS.value]["INVENTORY_ENDPOINT"]
                == list_value
            )
            assert "inv-secret" not in list_value
        finally:
            sep_settings._set_snapshot({})

    async def test_complex_field_renders_as_mapping(
        self, api_admin_client: TestClient
    ) -> None:
        """Emit ``SEPSettings.APPS`` as a structured value, not a repr blob."""
        export = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
        plugins = export[SettingClassEnum.SEP_SETTINGS.value]["APPS"]
        assert isinstance(plugins, list)
        if plugins:
            assert isinstance(plugins[0], dict)


@pytest.mark.asyncio
class TestSepConfigExportTasksFanOut:
    """Tests for Tasks fan-out success and upstream failure on config export."""

    async def test_tasks_settings_merged_from_fan_out(
        self, api_admin_client: TestClient
    ) -> None:
        """Place Tasks LIST values under the ``TasksSettings`` top-level key."""
        export = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
        tasks_block = export[SettingClassEnum.TASKS_SETTINGS.value]
        assert (
            tasks_block["STALENESS_THRESHOLD_SECONDS"]
            == SAMPLE_STALENESS_THRESHOLD_SECONDS
        )
        assert tasks_block["API_SECRET"] == REDACTED_SECRET

    async def test_nomad_endpoint_leaf_redacted_in_tasks_export_block(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Merge a redacted ``NOMAD__endpoint`` LIST value into the export YAML."""
        redacted_endpoint = "http://nomad-user:****@nomad.internal:4646/"
        mock_tasks_api.get.return_value = {
            "groups": [
                {
                    "setting_class": SettingClassEnum.TASKS_SETTINGS.value,
                    "settings": [
                        {
                            "setting_class": SettingClassEnum.TASKS_SETTINGS.value,
                            "key": "NOMAD__endpoint",
                            "key_path": ["NOMAD", "endpoint"],
                            "value": redacted_endpoint,
                            "default_value": None,
                            "type": "Url",
                            "reload": "hot",
                            "description": None,
                            "is_secret": False,
                            "is_complex": False,
                            "has_override": True,
                        }
                    ],
                }
            ]
        }
        yaml_text = api_admin_client.get(EXPORT_URL).text
        export = yaml.safe_load(yaml_text)
        assert (
            export[SettingClassEnum.TASKS_SETTINGS.value]["NOMAD__endpoint"]
            == redacted_endpoint
        )
        assert "nomad-secret" not in yaml_text
        assert "****" in yaml_text

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

    async def test_tasks_malformed_group_returns_502(
        self,
        api_admin_client: TestClient,
        mock_tasks_api: AsyncMock,
    ) -> None:
        """Return ``502`` when a Tasks LIST group is not an object."""
        mock_tasks_api.get.return_value = {"groups": ["not-a-group"]}
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert (
            response.json()["detail"] == "Tasks settings LIST group is not an object."
        )

    async def test_tasks_group_missing_setting_class_returns_502(
        self,
        api_admin_client: TestClient,
        mock_tasks_api: AsyncMock,
    ) -> None:
        """Return ``502`` when a Tasks LIST group omits ``setting_class``."""
        mock_tasks_api.get.return_value = {"groups": [{"settings": []}]}
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert (
            response.json()["detail"]
            == "Tasks settings LIST group missing 'setting_class'."
        )

    async def test_tasks_group_missing_settings_returns_502(
        self,
        api_admin_client: TestClient,
        mock_tasks_api: AsyncMock,
    ) -> None:
        """Return ``502`` when a Tasks LIST group omits ``settings``."""
        mock_tasks_api.get.return_value = {
            "groups": [{"setting_class": SettingClassEnum.TASKS_SETTINGS.value}]
        }
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "missing 'settings'" in response.json()["detail"]


SEP_CLASS = SettingClassEnum.SEP_SETTINGS.value
SNIPPETS_CLASS = SettingClassEnum.SNIPPETS_SETTINGS.value
ALERTS_CLASS = SettingClassEnum.ALERTS_SETTINGS.value
HEALTH_REPORT_CLASS = SettingClassEnum.HEALTH_REPORT_SETTINGS.value
SETTINGS_CLASS = SettingClassEnum.SETTINGS.value
ALERT_CLASS = SettingClassEnum.ALERT_SETTINGS.value
TASKS_CLASS = SettingClassEnum.TASKS_SETTINGS.value
FULL_EXPORT_CLASSES = {
    SEP_CLASS,
    SNIPPETS_CLASS,
    ALERTS_CLASS,
    HEALTH_REPORT_CLASS,
    SETTINGS_CLASS,
    ALERT_CLASS,
    TASKS_CLASS,
}
TASKS_SAMPLE_KEY = "STALENESS_THRESHOLD_SECONDS"
MIN_MULTI_KEYS = 2


def _one_sep_key(client: TestClient) -> str:
    """Return one real key on ``SEPSettings`` as seen by the LIST projection."""
    keys = _list_keys_by_class(client)[SEP_CLASS]
    assert keys, "expected SEPSettings to expose at least one LIST key"
    return sorted(keys)[0]


@pytest.mark.asyncio
class TestSepConfigExportFilter:
    """Tests for the ``keys`` selector filter on ``GET .../settings/export``."""

    async def test_omitted_keys_returns_full_export(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Yield the full export and fan out once when ``keys`` is omitted."""
        response = api_admin_client.get(EXPORT_URL)
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload) == FULL_EXPORT_CLASSES
        mock_tasks_api.get.assert_awaited_once_with("/admin/settings/")

    async def test_single_key_selector_returns_only_that_key(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Return only that class block with only that key for ``SEPSettings.<key>``."""
        key = _one_sep_key(api_admin_client)
        # _one_sep_key hit the LIST endpoint, which fans out to Tasks; reset so the
        # assert_not_called below measures only the export request.
        mock_tasks_api.get.reset_mock()
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": f"{SEP_CLASS}.{key}"}
        )
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload) == {SEP_CLASS}
        assert set(payload[SEP_CLASS]) == {key}
        mock_tasks_api.get.assert_not_called()

    async def test_key_selector_tolerates_incidental_whitespace(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Strip whitespace around the key segment so ``Class. KEY`` still resolves."""
        key = _one_sep_key(api_admin_client)
        mock_tasks_api.get.reset_mock()
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": f"{SEP_CLASS}. {key} "}
        )
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload) == {SEP_CLASS}
        assert set(payload[SEP_CLASS]) == {key}

    async def test_whole_class_selector_keeps_all_keys(
        self, api_admin_client: TestClient
    ) -> None:
        """Keep every LIST key for the class on a bare ``SnippetsSettings`` selector."""
        list_keys = _list_keys_by_class(api_admin_client)
        response = api_admin_client.get(EXPORT_URL, params={"keys": SNIPPETS_CLASS})
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload) == {SNIPPETS_CLASS}
        assert set(payload[SNIPPETS_CLASS]) == list_keys[SNIPPETS_CLASS]

    async def test_mixed_class_and_key_selectors(
        self, api_admin_client: TestClient
    ) -> None:
        """Yield exactly two blocks for ``SEPSettings.<key>`` plus whole ``AlertsSettings``."""
        key = _one_sep_key(api_admin_client)
        list_keys = _list_keys_by_class(api_admin_client)
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": [f"{SEP_CLASS}.{key}", ALERTS_CLASS]}
        )
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload) == {SEP_CLASS, ALERTS_CLASS}
        assert set(payload[SEP_CLASS]) == {key}
        assert set(payload[ALERTS_CLASS]) == list_keys[ALERTS_CLASS]

    async def test_block_order_is_canonical_not_selector_order(
        self, api_admin_client: TestClient
    ) -> None:
        """Order blocks canonically (SEP before Tasks) regardless of input order."""
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": [TASKS_CLASS, SEP_CLASS]}
        )
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert list(payload) == [SEP_CLASS, TASKS_CLASS]

    async def test_block_order_places_app_owned_before_tasks(
        self, api_admin_client: TestClient
    ) -> None:
        """Place app-owned blocks after core classes and before Tasks."""
        response = api_admin_client.get(
            EXPORT_URL,
            params={"keys": [TASKS_CLASS, ALERTS_CLASS, SEP_CLASS]},
        )
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert list(payload) == [SEP_CLASS, ALERTS_CLASS, TASKS_CLASS]

    async def test_core_alert_block_precedes_app_owned_alerts_block(
        self, api_admin_client: TestClient
    ) -> None:
        """Keep the core ``AlertSettings`` block ahead of the app-owned ``AlertsSettings``."""
        response = api_admin_client.get(
            EXPORT_URL,
            params={"keys": [ALERTS_CLASS, TASKS_CLASS, ALERT_CLASS]},
        )
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert list(payload) == [ALERT_CLASS, ALERTS_CLASS, TASKS_CLASS]

    async def test_alert_settings_whole_class_selector(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Export every ``AlertSettings`` key without fanning out to Tasks."""
        list_keys = _list_keys_by_class(api_admin_client)
        mock_tasks_api.get.reset_mock()
        response = api_admin_client.get(EXPORT_URL, params={"keys": ALERT_CLASS})
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload) == {ALERT_CLASS}
        assert set(payload[ALERT_CLASS]) == list_keys[ALERT_CLASS]
        mock_tasks_api.get.assert_not_called()

    async def test_alert_settings_key_selector_skips_tasks_fan_out(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Export one ``AlertSettings`` key with no upstream Tasks call."""
        mock_tasks_api.get.reset_mock()
        response = api_admin_client.get(
            EXPORT_URL,
            params={"keys": f"{ALERT_CLASS}.SOURCE_PREFIX"},
        )
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload) == {ALERT_CLASS}
        assert set(payload[ALERT_CLASS]) == {"SOURCE_PREFIX"}
        mock_tasks_api.get.assert_not_called()

    async def test_whole_class_dominates_overlapping_key(
        self, api_admin_client: TestClient
    ) -> None:
        """Keep all keys for ``SEPSettings`` + ``SEPSettings.<key>`` (whole class wins)."""
        key = _one_sep_key(api_admin_client)
        list_keys = _list_keys_by_class(api_admin_client)
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": [SEP_CLASS, f"{SEP_CLASS}.{key}"]}
        )
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload[SEP_CLASS]) == list_keys[SEP_CLASS]

    @pytest.mark.parametrize(
        "params",
        [
            {"keys": [SEP_CLASS, f"{SEP_CLASS}.NOT_A_KEY"]},
            {"keys": [f"{SEP_CLASS}.NOT_A_KEY", SEP_CLASS]},
        ],
    )
    async def test_whole_class_does_not_absorb_invalid_sibling_key(
        self,
        api_admin_client: TestClient,
        mock_tasks_api: AsyncMock,
        params: dict[str, Any],
    ) -> None:
        """Reject a bad ``Class.KEY`` even when the whole class is also requested.

        Order-independent: a whole-class selector dominates output but must not
        silently absorb a typo'd sibling key (AC 6).
        """
        response = api_admin_client.get(EXPORT_URL, params=params)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert f"{SEP_CLASS}.NOT_A_KEY" in response.json()["detail"]
        mock_tasks_api.get.assert_not_called()

    async def test_whole_tasks_class_does_not_absorb_invalid_sibling_key(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Reject a bad ``TasksSettings.KEY`` after the fan-out runs, despite whole class."""
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": [TASKS_CLASS, f"{TASKS_CLASS}.NOT_A_KEY"]}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert f"{TASKS_CLASS}.NOT_A_KEY" in response.json()["detail"]
        mock_tasks_api.get.assert_awaited_once_with("/admin/settings/")

    async def test_no_tasks_selector_skips_fan_out(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Make no upstream call and emit no Tasks block when the filter excludes Tasks."""
        response = api_admin_client.get(EXPORT_URL, params={"keys": SNIPPETS_CLASS})
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert TASKS_CLASS not in payload
        mock_tasks_api.get.assert_not_called()

    async def test_tasks_selector_triggers_filtered_fan_out(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Fan out once and keep only the requested Tasks key for a Tasks key selector."""
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": f"{TASKS_CLASS}.{TASKS_SAMPLE_KEY}"}
        )
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload) == {TASKS_CLASS}
        assert set(payload[TASKS_CLASS]) == {TASKS_SAMPLE_KEY}
        mock_tasks_api.get.assert_awaited_once_with("/admin/settings/")

    async def test_unknown_class_returns_400_no_fan_out(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Fail 400 naming the selector on an unknown class name, with no upstream call."""
        response = api_admin_client.get(EXPORT_URL, params={"keys": "Nope.KEY"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Nope.KEY" in response.json()["detail"]
        mock_tasks_api.get.assert_not_called()

    async def test_unknown_sep_key_returns_400_no_fan_out(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Fail 400 naming the selector on an unknown SEP key, with no upstream call."""
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": f"{SEP_CLASS}.NOT_A_KEY"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert f"{SEP_CLASS}.NOT_A_KEY" in response.json()["detail"]
        mock_tasks_api.get.assert_not_called()

    async def test_unknown_tasks_key_returns_400_after_fan_out(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Fail 400 naming the selector on an unknown Tasks key (fan-out did run)."""
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": f"{TASKS_CLASS}.NOT_A_KEY"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert f"{TASKS_CLASS}.NOT_A_KEY" in response.json()["detail"]
        mock_tasks_api.get.assert_awaited_once_with("/admin/settings/")

    @pytest.mark.parametrize(
        "params",
        [
            {"keys": ""},
            {"keys": [SEP_CLASS, ""]},
            {"keys": ".LOG_LEVEL"},
            {"keys": f"{SEP_CLASS}."},
        ],
    )
    async def test_blank_or_malformed_selector_returns_400(
        self, api_admin_client: TestClient, params: dict[str, Any]
    ) -> None:
        """Reject blank, empty-class, and empty-key selectors with 400."""
        response = api_admin_client.get(EXPORT_URL, params=params)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_static_invalid_precedes_fan_out(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Fail 400 before any fan-out when an unknown class sits beside a valid Tasks selector."""
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": ["Nope", TASKS_CLASS]}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Nope" in response.json()["detail"]
        mock_tasks_api.get.assert_not_called()

    async def test_unknown_tasks_key_with_upstream_down_returns_502(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Surface an unknown Tasks key as 502, not 400, when Tasks is unreachable."""
        mock_tasks_api.get.side_effect = OSError("connection refused")
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": f"{TASKS_CLASS}.NOT_A_KEY"}
        )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    async def test_filtered_secret_still_redacted(
        self, api_admin_client: TestClient, mocker
    ) -> None:
        """Keep the value redacted in the YAML when filtering to a secret-bearing field."""
        _configure_health_report_upload(mocker)
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": HEALTH_REPORT_CLASS}
        )
        assert response.status_code == status.HTTP_200_OK
        assert "local-secret" not in response.text
        payload = yaml.safe_load(response.text)
        assert payload[HEALTH_REPORT_CLASS]["api_key"] == REDACTED_SECRET

    async def test_class_segment_tolerates_incidental_whitespace(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Strip whitespace around the class segment for both whole-class and key selectors."""
        key = _one_sep_key(api_admin_client)
        mock_tasks_api.get.reset_mock()

        whole = api_admin_client.get(EXPORT_URL, params={"keys": f" {SNIPPETS_CLASS} "})
        assert whole.status_code == status.HTTP_200_OK
        assert set(yaml.safe_load(whole.text)) == {SNIPPETS_CLASS}

        keyed = api_admin_client.get(
            EXPORT_URL, params={"keys": f" {SEP_CLASS} . {key} "}
        )
        assert keyed.status_code == status.HTTP_200_OK
        keyed_payload = yaml.safe_load(keyed.text)
        assert set(keyed_payload) == {SEP_CLASS}
        assert set(keyed_payload[SEP_CLASS]) == {key}
        mock_tasks_api.get.assert_not_called()

    async def test_multiple_keys_same_class_kept_together(
        self, api_admin_client: TestClient
    ) -> None:
        """Accumulate multiple ``Class.KEY`` selectors for one class into a single block."""
        sep_keys = sorted(_list_keys_by_class(api_admin_client)[SEP_CLASS])
        assert len(sep_keys) >= MIN_MULTI_KEYS, (
            "expected SEPSettings to expose at least two LIST keys"
        )
        first, second = sep_keys[0], sep_keys[1]
        response = api_admin_client.get(
            EXPORT_URL,
            params={"keys": [f"{SEP_CLASS}.{first}", f"{SEP_CLASS}.{second}"]},
        )
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload) == {SEP_CLASS}
        assert set(payload[SEP_CLASS]) == {first, second}

    async def test_duplicate_selectors_are_benign(
        self, api_admin_client: TestClient
    ) -> None:
        """Treat repeated whole-class and key selectors as the single-selector case."""
        key = _one_sep_key(api_admin_client)
        list_keys = _list_keys_by_class(api_admin_client)

        dup_class = api_admin_client.get(
            EXPORT_URL, params={"keys": [SNIPPETS_CLASS, SNIPPETS_CLASS]}
        )
        assert dup_class.status_code == status.HTTP_200_OK
        dup_class_payload = yaml.safe_load(dup_class.text)
        assert set(dup_class_payload) == {SNIPPETS_CLASS}
        assert set(dup_class_payload[SNIPPETS_CLASS]) == list_keys[SNIPPETS_CLASS]

        dup_key = api_admin_client.get(
            EXPORT_URL,
            params={"keys": [f"{SEP_CLASS}.{key}", f"{SEP_CLASS}.{key}"]},
        )
        assert dup_key.status_code == status.HTTP_200_OK
        dup_key_payload = yaml.safe_load(dup_key.text)
        assert set(dup_key_payload) == {SEP_CLASS}
        assert set(dup_key_payload[SEP_CLASS]) == {key}

    async def test_filtered_tasks_secret_still_redacted(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Keep the Tasks secret redacted when filtering to a single Tasks secret key."""
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": f"{TASKS_CLASS}.API_SECRET"}
        )
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload) == {TASKS_CLASS}
        assert set(payload[TASKS_CLASS]) == {"API_SECRET"}
        assert payload[TASKS_CLASS]["API_SECRET"] == REDACTED_SECRET
        mock_tasks_api.get.assert_awaited_once_with("/admin/settings/")

    async def test_bare_tasks_class_keeps_all_keys(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Keep every fetched Tasks key for a bare ``TasksSettings`` selector and fan out once."""
        response = api_admin_client.get(EXPORT_URL, params={"keys": TASKS_CLASS})
        assert response.status_code == status.HTTP_200_OK
        payload = yaml.safe_load(response.text)
        assert set(payload) == {TASKS_CLASS}
        assert set(payload[TASKS_CLASS]) == {TASKS_SAMPLE_KEY, "API_SECRET"}
        mock_tasks_api.get.assert_awaited_once_with("/admin/settings/")

    async def test_class_name_match_is_case_sensitive(
        self, api_admin_client: TestClient, mock_tasks_api: AsyncMock
    ) -> None:
        """Reject a lowercased class name as an unknown selector with no fan-out."""
        response = api_admin_client.get(
            EXPORT_URL, params={"keys": f"{SEP_CLASS.lower()}.LOG_LEVEL"}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert SEP_CLASS.lower() in response.json()["detail"]
        mock_tasks_api.get.assert_not_called()

    async def test_filtered_block_equals_full_export_block(
        self, api_admin_client: TestClient
    ) -> None:
        """Emit a whole-class block identical to its slice of the unfiltered export."""
        full = yaml.safe_load(api_admin_client.get(EXPORT_URL).text)
        filtered = yaml.safe_load(
            api_admin_client.get(EXPORT_URL, params={"keys": SNIPPETS_CLASS}).text
        )
        assert filtered[SNIPPETS_CLASS] == full[SNIPPETS_CLASS]
