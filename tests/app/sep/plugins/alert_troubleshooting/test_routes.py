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

"""Test the alert troubleshooting plugin routes."""

from fastapi import status
from starlette.testclient import TestClient

from app.sep.main import sep_app
from app.sep.models import AlertServiceType
from app.sep.plugins.alert_troubleshooting.deps import (
    AlertInfo,
    get_troubleshooting_index_context,
)


def _override_context(grouped_alerts):
    """Build a context override with the given grouped alerts."""

    async def _mock_context():
        return {
            "grouped_alerts": grouped_alerts,
            "alert_service_types": list(AlertServiceType),
        }

    return _mock_context


class TestTroubleshootingIndex:
    """Test the alert troubleshooting index route."""

    def test_index_returns_200(self, test_client: TestClient):
        """Assert GET /alert-troubleshooting/ returns 200."""
        grouped = {
            AlertServiceType.MYSQL: [
                AlertInfo(name="MySQLSlowQueries", label="MySQL Slow Queries"),
            ],
        }
        sep_app.dependency_overrides[get_troubleshooting_index_context] = (
            _override_context(grouped)
        )
        response = test_client.get("/alert-troubleshooting/")
        assert response.status_code == status.HTTP_200_OK

    def test_index_renders_alert_names(self, test_client: TestClient):
        """Assert the response includes alert display names."""
        grouped = {
            AlertServiceType.POSTGRESQL: [
                AlertInfo(
                    name="PostgreSQLLockConflicts",
                    label="PostgreSQL Lock Conflicts",
                ),
            ],
        }
        sep_app.dependency_overrides[get_troubleshooting_index_context] = (
            _override_context(grouped)
        )
        response = test_client.get("/alert-troubleshooting/")
        assert "PostgreSQL Lock Conflicts" in response.text

    def test_index_renders_service_type_header(self, test_client: TestClient):
        """Assert the response includes service type section headers."""
        grouped = {
            AlertServiceType.MYSQL: [
                AlertInfo(name="MySQLSlowQueries", label="MySQL Slow Queries"),
            ],
        }
        sep_app.dependency_overrides[get_troubleshooting_index_context] = (
            _override_context(grouped)
        )
        response = test_client.get("/alert-troubleshooting/")
        assert "MySQL" in response.text

    def test_index_empty_state(self, test_client: TestClient):
        """Assert the empty state message renders when no alerts exist."""
        sep_app.dependency_overrides[get_troubleshooting_index_context] = (
            _override_context({})
        )
        response = test_client.get("/alert-troubleshooting/")
        assert response.status_code == status.HTTP_200_OK
        assert "No alert troubleshooting guides" in response.text

    def test_index_alert_links_to_detail(self, test_client: TestClient):
        """Assert alert links point to the detail page URL."""
        grouped = {
            AlertServiceType.GENERIC: [
                AlertInfo(name="HighCPUUsage", label="High CPU Usage"),
            ],
        }
        sep_app.dependency_overrides[get_troubleshooting_index_context] = (
            _override_context(grouped)
        )
        response = test_client.get("/alert-troubleshooting/")
        assert "/alert-troubleshooting/HighCPUUsage" in response.text
