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

"""Tests for the alert_troubleshooting plugin schema."""

from fastapi import status

from app.sep.apps.alert_troubleshooting.schema import (
    ALERT_TROUBLESHOOTING_PLUGIN_SCHEMA,
)


class TestStaticSchema:
    """Tests against the in-memory ALERT_TROUBLESHOOTING_PLUGIN_SCHEMA constant."""

    def test_has_correct_name(self):
        """Check the app schema identifies as alert_troubleshooting."""
        assert ALERT_TROUBLESHOOTING_PLUGIN_SCHEMA.name == "alert_troubleshooting"
        assert (
            ALERT_TROUBLESHOOTING_PLUGIN_SCHEMA.display_name == "Alert Troubleshooting"
        )

    def test_has_no_forms(self):
        """Check the app schema declares no editable forms (browse-only plugin)."""
        assert ALERT_TROUBLESHOOTING_PLUGIN_SCHEMA.forms == []

    def test_listview_columns(self):
        """ListView columns match the AlertGroup response shape."""
        columns = ALERT_TROUBLESHOOTING_PLUGIN_SCHEMA.list_view.columns
        column_keys = [col.key for col in columns]
        assert "service_type" in column_keys
        assert "label" in column_keys


class TestSchemaEndpoint:
    """Tests for the /api/apps/alert_troubleshooting/schema HTTP endpoint."""

    def test_returns_plugin_schema(self, test_client):
        """GET /api/apps/alert_troubleshooting/schema returns the plugin metadata."""
        response = test_client.get("/api/apps/alert_troubleshooting/schema")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "alert_troubleshooting"
        assert data["display_name"] == "Alert Troubleshooting"
