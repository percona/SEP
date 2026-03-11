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

import pytest
from fastapi import status

from app.sep.main import sep_app
from app.sep.plugins.alerts.deps import get_alerts_index_context
from app.sep.plugins.alerts.models import AlertSeverity, AlertTemplate, ServiceType

_POPULATED_CONTEXT = {
    "user": "test-user",
    "all_templates": [
        AlertTemplate(
            name="High CPU",
            service_type=ServiceType.GENERIC,
            expression="cpu > 80",
            default_threshold=80.0,
            severity=AlertSeverity.WARNING,
            description="CPU usage is above threshold.",
            summary="High CPU on {{ $labels.instance }}",
        ),
    ],
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
