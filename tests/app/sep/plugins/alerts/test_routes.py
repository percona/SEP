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

"""Define tests for the app.sep.plugins.alerts.routes module."""

from collections.abc import Mapping
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from fastapi.exceptions import HTTPException

from app.sep.clients.pmm import Folder, PMMRemoteAPI
from app.sep.main import sep_app
from app.sep.plugins.alerts.deps import (
    get_alert_templates,
    get_alerts_index_context,
    get_or_create_alert_folder,
    get_pmm_api,
    get_pmm_present_names,
)
from app.sep.plugins.alerts.models import AlertSeverity, AlertTemplate, ServiceType

_TEMPLATE_A = AlertTemplate(
    name="High CPU",
    service_type=ServiceType.GENERIC,
    expression="cpu > 80",
    default_threshold=80.0,
    severity=AlertSeverity.WARNING,
    description="CPU usage is above threshold.",
    summary="High CPU on {{ $labels.instance }}",
)

_TEMPLATE_B = AlertTemplate(
    name="Disk Full",
    service_type=ServiceType.GENERIC,
    expression="disk_used_percent > 90",
    default_threshold=90.0,
    severity=AlertSeverity.CRITICAL,
    description="Disk usage is above threshold.",
    summary="Disk full on {{ $labels.instance }}",
)

_ALERT_TEMPLATES: Mapping[ServiceType, tuple[AlertTemplate, ...]] = {
    ServiceType.GENERIC: (_TEMPLATE_A, _TEMPLATE_B),
    ServiceType.MYSQL: (),
    ServiceType.MONGODB: (),
    ServiceType.POSTGRESQL: (),
}

_POPULATED_CONTEXT = {
    "user": "test-user",
    "all_templates": [_TEMPLATE_A],
    "service_types": list(ServiceType),
    "pmm_present_names": {"High CPU"},
    "alert_templates": {},
}

_EMPTY_CONTEXT = {
    "user": "test-user",
    "all_templates": [],
    "service_types": list(ServiceType),
    "pmm_present_names": None,
    "alert_templates": {},
}

_FOLDER = Folder(uid="folder-1", title="SEP Alerts", id=1)


@pytest.fixture
def _mock_alerts_index_context():
    """Mock the alerts index context dependency with populated data."""
    sep_app.dependency_overrides[get_alerts_index_context] = lambda: _POPULATED_CONTEXT
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def _mock_alerts_empty_context():
    """Mock the alerts index context dependency with empty data."""
    sep_app.dependency_overrides[get_alerts_index_context] = lambda: _EMPTY_CONTEXT
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_pmm_api():
    """Return a mock PMMRemoteAPI and wire it into dependency overrides."""
    mock = AsyncMock(spec=PMMRemoteAPI)
    mock.list_folders.return_value = [_FOLDER]
    mock.list_templates.return_value = []
    mock.create_template.return_value = AsyncMock()
    mock.create_rule.return_value = AsyncMock()
    sep_app.dependency_overrides[get_pmm_api] = lambda: mock
    sep_app.dependency_overrides[get_alert_templates] = lambda: _ALERT_TEMPLATES
    sep_app.dependency_overrides[get_or_create_alert_folder] = lambda: _FOLDER
    sep_app.dependency_overrides[get_pmm_present_names] = lambda: set()
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def _mock_pmm_not_configured():
    """Mock PMM as not configured (returns None)."""
    sep_app.dependency_overrides[get_pmm_api] = lambda: None
    sep_app.dependency_overrides[get_alert_templates] = lambda: _ALERT_TEMPLATES
    sep_app.dependency_overrides[get_or_create_alert_folder] = lambda: None
    sep_app.dependency_overrides[get_pmm_present_names] = lambda: None
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_alerts_index_context")
def test_alerts_index(test_client):
    """Assert GET /alerts/ returns 200 with the alert templates page."""
    response = test_client.get("/alerts/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "<title>Alert Templates" in response.text


@pytest.mark.usefixtures("_mock_alerts_index_context")
def test_alerts_index_contains_template_name(test_client):
    """Assert the response includes the alert template name."""
    response = test_client.get("/alerts/")
    assert "High CPU" in response.text


@pytest.mark.usefixtures("_mock_alerts_index_context")
def test_alerts_index_contains_filter_tabs(test_client):
    """Assert the response includes service filter tabs."""
    response = test_client.get("/alerts/")
    assert "Generic" in response.text
    assert "MySQL" in response.text


@pytest.mark.usefixtures("_mock_alerts_empty_context")
def test_alerts_index_empty_state(test_client):
    """Assert the empty state message renders when no templates exist."""
    response = test_client.get("/alerts/")
    assert response.status_code == status.HTTP_200_OK
    assert "No alert templates found." in response.text
    assert "alerts-table" not in response.text


class TestAlertsPush:
    """Test the POST /alerts/push endpoint."""

    _EXPECTED_PUSH_COUNT = 2

    def test_push_success(self, test_client, mock_pmm_api):
        """Assert pushing templates returns per-template success results."""
        response = test_client.post(
            "/alerts/push",
            data={"selected_templates": ["High CPU", "Disk Full"]},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["results"]) == self._EXPECTED_PUSH_COUNT
        assert all(r["status"] == "success" for r in data["results"])
        assert mock_pmm_api.create_template.await_count == self._EXPECTED_PUSH_COUNT
        assert mock_pmm_api.create_rule.await_count == self._EXPECTED_PUSH_COUNT

    @pytest.mark.usefixtures("_mock_pmm_not_configured")
    def test_push_pmm_not_configured(self, test_client):
        """Assert 503 is returned when PMM is not configured."""
        response = test_client.post(
            "/alerts/push",
            data={"selected_templates": ["High CPU"]},
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["error"] == "PMM is not configured"

    def test_push_already_present(self, test_client, mock_pmm_api):
        """Assert templates already in PMM are skipped."""
        sep_app.dependency_overrides[get_pmm_present_names] = lambda: {"High CPU"}

        response = test_client.post(
            "/alerts/push",
            data={"selected_templates": ["High CPU"]},
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "skipped"
        assert result["message"] == "Already present in PMM"
        mock_pmm_api.create_template.assert_not_awaited()

    def test_push_template_not_found(self, test_client, mock_pmm_api):
        """Assert an error result for a template name that does not exist."""
        response = test_client.post(
            "/alerts/push",
            data={"selected_templates": ["Nonexistent Template"]},
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "error"
        assert result["message"] == "Template not found"

    def test_push_pmm_api_error(self, test_client, mock_pmm_api):
        """Assert per-template error when PMM API raises an exception."""
        mock_pmm_api.create_template.side_effect = HTTPException(
            status_code=502, detail="Bad Gateway"
        )

        response = test_client.post(
            "/alerts/push",
            data={"selected_templates": ["High CPU"]},
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "error"
        assert "Bad Gateway" in result["message"]

    def test_push_returns_502_when_folder_unavailable(self, test_client, mock_pmm_api):
        """Assert 502 is returned when the alert folder cannot be resolved."""
        sep_app.dependency_overrides[get_or_create_alert_folder] = lambda: None

        response = test_client.post(
            "/alerts/push",
            data={"selected_templates": ["High CPU"]},
        )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json()["error"] == "Failed to access PMM alert folder"

    def test_push_rule_failure_reports_orphaned_template(
        self, test_client, mock_pmm_api
    ):
        """Assert error message indicates template was created when rule fails."""
        mock_pmm_api.create_rule.side_effect = HTTPException(
            status_code=502, detail="Rule creation failed"
        )

        response = test_client.post(
            "/alerts/push",
            data={"selected_templates": ["High CPU"]},
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "error"
        assert "Template created but rule failed" in result["message"]
