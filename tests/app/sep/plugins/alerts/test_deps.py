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

"""Define tests for the app.sep.plugins.alerts.deps module."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.exceptions import HTTPException

from app.sep.clients.pmm import AlertTemplate as PMMAlertTemplate
from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.plugins.alerts.deps import (
    get_alerts_index_context,
    get_pmm_api,
    get_pmm_present_names,
)
from app.sep.plugins.alerts.models import (
    AlertSeverity,
    AlertTemplate,
    ServiceType,
)


def _make_alert_template(**overrides: object) -> AlertTemplate:
    defaults = {
        "name": "High CPU",
        "service_type": ServiceType.GENERIC,
        "expression": "cpu > 80",
        "default_threshold": 80.0,
        "severity": AlertSeverity.WARNING,
        "description": "CPU usage is above threshold.",
        "summary": "High CPU on {{ $labels.instance }}",
    }
    defaults.update(overrides)
    return AlertTemplate(**defaults)


class TestGetPmmApi:
    """Test the `get_pmm_api` dependency."""

    @pytest.mark.asyncio
    async def test_returns_none_when_endpoint_not_configured(self):
        """Assert `None` is returned when PMM endpoint is not set."""
        with patch("app.sep.plugins.alerts.deps.sep_settings") as mock_settings:
            mock_settings.PMM.endpoint = None
            mock_settings.PMM.api_key = None
            result = await get_pmm_api()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_api_key_not_configured(self):
        """Assert `None` is returned when PMM API key is not set."""
        with patch("app.sep.plugins.alerts.deps.sep_settings") as mock_settings:
            mock_settings.PMM.endpoint = "https://pmm.example.com"
            mock_settings.PMM.api_key = None
            result = await get_pmm_api()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_client_when_configured(self):
        """Assert a `PMMRemoteAPI` is returned when PMM is configured."""
        mock_client = AsyncMock(spec=PMMRemoteAPI)
        with (
            patch("app.sep.plugins.alerts.deps.sep_settings") as mock_settings,
            patch("app.sep.plugins.alerts.deps.settings") as mock_global_settings,
        ):
            mock_settings.PMM.endpoint = "https://pmm.example.com"
            mock_settings.PMM.api_key = "secret-key"
            mock_settings.PMM.verify_ssl = True
            mock_global_settings.get_remote_api = AsyncMock(return_value=mock_client)
            result = await get_pmm_api()
        assert result is mock_client
        mock_global_settings.get_remote_api.assert_awaited_once_with(
            PMMRemoteAPI,
            endpoint="https://pmm.example.com",
            api_key="secret-key",
            verify_ssl=True,
        )


class TestGetPmmPresentNames:
    """Test the `get_pmm_present_names` dependency."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_pmm_api(self):
        """Assert `None` is returned when the PMM API is not available."""
        result = await get_pmm_present_names(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_set_of_names_on_success(self):
        """Assert a set of template names is returned on success."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_templates.return_value = [
            PMMAlertTemplate(name="template-a", summary="A", template="yaml"),
            PMMAlertTemplate(name="template-b", summary="B", template="yaml"),
        ]
        result = await get_pmm_present_names(mock_api)
        assert result == {"template-a", "template-b"}

    @pytest.mark.asyncio
    async def test_returns_empty_set_when_no_templates(self):
        """Assert an empty set is returned when PMM has no templates."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_templates.return_value = []
        result = await get_pmm_present_names(mock_api)
        assert result == set()

    @pytest.mark.asyncio
    async def test_returns_none_on_connection_error(self):
        """Assert `None` is returned when PMM is unreachable."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_templates.side_effect = OSError("unreachable")
        result = await get_pmm_present_names(mock_api)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_http_exception(self):
        """Assert `None` is returned on HTTP error from PMM."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_templates.side_effect = HTTPException(
            status_code=502, detail="Bad Gateway"
        )
        result = await get_pmm_present_names(mock_api)
        assert result is None


class TestGetAlertsIndexContext:
    """Test the `get_alerts_index_context` dependency."""

    @pytest.mark.asyncio
    async def test_assembles_context_with_all_fields(self):
        """Assert the context contains all expected keys."""
        base_context = {"user": "test-user", "plugins": []}
        templates_by_service = {
            ServiceType.GENERIC: (_make_alert_template(),),
            ServiceType.MYSQL: (
                _make_alert_template(
                    name="Slow Queries", service_type=ServiceType.MYSQL
                ),
            ),
            ServiceType.MONGODB: (),
            ServiceType.POSTGRESQL: (),
        }
        pmm_names = {"High CPU"}

        result = await get_alerts_index_context(
            base_context, templates_by_service, pmm_names
        )

        assert "all_templates" in result
        assert "service_types" in result
        assert "pmm_present_names" in result
        expected_template_count = sum(len(ts) for ts in templates_by_service.values())
        assert len(result["all_templates"]) == expected_template_count
        assert result["service_types"] == list(ServiceType)
        assert result["pmm_present_names"] is pmm_names
        assert result["user"] == "test-user"

    @pytest.mark.asyncio
    async def test_pmm_present_names_can_be_none(self):
        """Assert the context works when PMM is unavailable."""
        base_context = {"user": "test-user"}
        templates_by_service = {svc: () for svc in ServiceType}

        result = await get_alerts_index_context(
            base_context, templates_by_service, None
        )

        assert result["pmm_present_names"] is None
        assert result["all_templates"] == []
