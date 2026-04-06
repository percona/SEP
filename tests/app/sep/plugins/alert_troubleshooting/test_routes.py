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

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException, status
from starlette.testclient import TestClient

from app.core.requests import RemoteAPI
from app.sep.deps import get_tasks_api
from app.sep.main import sep_app
from app.sep.models import AlertServiceType
from app.sep.plugins.alert_troubleshooting.deps import (
    AlertInfo,
    get_ajax_executable_snippet,
    get_ajax_execution_request_meta,
    get_troubleshooting_detail_context,
    get_troubleshooting_index_context,
)
from app.sep.snippets.models.snippet import SnippetExecutionMeta

MOCK_TASK_ID = 42


def _override_context(grouped_alerts):
    """Build a context override with the given grouped alerts."""

    async def _mock_context():
        return {
            "grouped_alerts": grouped_alerts,
            "alert_service_types": list(AlertServiceType),
            "base_uri": "/alert-troubleshooting",
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
        assert "/alert-troubleshooting/generic/HighCPUUsage" in response.text


def _override_detail_context(alert_info, snippets, executor_hosts):
    """Build a detail context override."""

    async def _mock_context():
        return {
            "alert_info": alert_info,
            "snippets": snippets,
            "executor_hosts": executor_hosts,
            "base_uri": "/alert-troubleshooting",
        }

    return _mock_context


class TestTroubleshootingDetail:
    """Test the alert troubleshooting detail route."""

    def test_detail_returns_200(self, test_client: TestClient):
        """Assert GET /{alert_name} returns 200 with valid context."""
        alert_info = AlertInfo(name="HighCPU", label="High CPU")
        sep_app.dependency_overrides[get_troubleshooting_detail_context] = (
            _override_detail_context(alert_info, [], [])
        )
        response = test_client.get("/alert-troubleshooting/generic/HighCPU")
        assert response.status_code == status.HTTP_200_OK

    def test_detail_renders_alert_label(self, test_client: TestClient):
        """Assert the detail page renders the alert display label."""
        alert_info = AlertInfo(name="MySQLSlowQueries", label="MySQL Slow Queries")
        sep_app.dependency_overrides[get_troubleshooting_detail_context] = (
            _override_detail_context(alert_info, [], [])
        )
        response = test_client.get("/alert-troubleshooting/mysql/MySQLSlowQueries")
        assert "MySQL Slow Queries" in response.text

    def test_detail_empty_snippets_shows_empty_state(self, test_client: TestClient):
        """Assert the detail page renders empty state when no snippets."""
        alert_info = AlertInfo(name="EmptyAlert", label="Empty Alert")
        sep_app.dependency_overrides[get_troubleshooting_detail_context] = (
            _override_detail_context(alert_info, [], [])
        )
        response = test_client.get("/alert-troubleshooting/generic/EmptyAlert")
        assert response.status_code == status.HTTP_200_OK
        assert "No snippets are associated" in response.text

    def test_detail_renders_executor_hosts(self, test_client: TestClient):
        """Assert the detail page renders executor host options."""
        alert_info = AlertInfo(name="HighCPU", label="High CPU")
        hosts = [{"value": "node-1", "label": "Node 1"}]
        sep_app.dependency_overrides[get_troubleshooting_detail_context] = (
            _override_detail_context(alert_info, [], hosts)
        )
        response = test_client.get("/alert-troubleshooting/generic/HighCPU")
        assert "Node 1" in response.text


class TestTroubleshootingExecute:
    """Test the AJAX snippet execution endpoint."""

    @staticmethod
    def _mock_snippet():
        """Create a mock executable snippet."""
        return SimpleNamespace(
            filename="test.sh",
            execution_task_name="run-command",
            can_execute=True,
            is_approved=True,
        )

    @staticmethod
    def _mock_meta():
        """Create a mock execution metadata."""
        return SnippetExecutionMeta(
            target="node-1",
            interpreter="bash",
            snippet_source="https://example.com/test.sh",
            snippet_filename="test.sh",
            md5_checksum="d" * 32,
        )

    def test_execute_success(self, test_client: TestClient):
        """Assert POST /execute/{filename} returns JSON with task ID."""
        mock_api = AsyncMock(spec=RemoteAPI)
        mock_api.post.return_value = {"id": MOCK_TASK_ID, "status": "running"}
        sep_app.dependency_overrides[get_tasks_api] = lambda: mock_api
        sep_app.dependency_overrides[get_ajax_executable_snippet] = self._mock_snippet
        sep_app.dependency_overrides[get_ajax_execution_request_meta] = self._mock_meta
        response = test_client.post(
            "/alert-troubleshooting/execute/test.sh",
            data={"-hostname-": "node-1", "csrf-token": "fake"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["task_id"] == MOCK_TASK_ID
        assert data["status"] == "submitted"

    def test_execute_tasks_api_error(self, test_client: TestClient):
        """Assert JSON error response when Tasks API fails."""
        mock_api = AsyncMock(spec=RemoteAPI)
        mock_api.post.side_effect = HTTPException(status_code=502, detail="Bad Gateway")
        sep_app.dependency_overrides[get_tasks_api] = lambda: mock_api
        sep_app.dependency_overrides[get_ajax_executable_snippet] = self._mock_snippet
        sep_app.dependency_overrides[get_ajax_execution_request_meta] = self._mock_meta
        response = test_client.post(
            "/alert-troubleshooting/execute/test.sh",
            data={"-hostname-": "node-1", "csrf-token": "fake"},
        )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "error" in response.json()


class TestTroubleshootingOutput:
    """Test the AJAX output polling endpoint."""

    def test_output_running(self, test_client: TestClient):
        """Assert running task returns status without output."""
        mock_api = AsyncMock(spec=RemoteAPI)
        mock_api.get.return_value = {"id": 1, "status": "running"}
        sep_app.dependency_overrides[get_tasks_api] = lambda: mock_api
        response = test_client.get("/alert-troubleshooting/output/1")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "running"

    def test_output_success(self, test_client: TestClient):
        """Assert successful task returns status and output text."""
        mock_api = AsyncMock(spec=RemoteAPI)
        mock_api.get.side_effect = [
            {"id": 1, "status": "success"},
            {"stdout.log": {"size": 16, "is_dir": False}},
        ]

        async def _mock_stream(path, **kwargs):
            yield b"query result OK"

        mock_api.stream = _mock_stream
        sep_app.dependency_overrides[get_tasks_api] = lambda: mock_api
        response = test_client.get("/alert-troubleshooting/output/1")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
        assert "query result OK" in data["output"]

    def test_output_failed(self, test_client: TestClient):
        """Assert failed task returns error status."""
        mock_api = AsyncMock(spec=RemoteAPI)
        mock_api.get.side_effect = [
            {"id": 1, "status": "failed"},
            {"stderr.log": {"size": 25, "is_dir": False}},
        ]

        async def _mock_stream(path, **kwargs):
            yield b"Error: connection refused"

        mock_api.stream = _mock_stream
        sep_app.dependency_overrides[get_tasks_api] = lambda: mock_api
        response = test_client.get("/alert-troubleshooting/output/1")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "failed"
        assert "connection refused" in data["output"]

    def test_output_tasks_api_error(self, test_client: TestClient):
        """Assert JSON error response when Tasks API returns an error."""
        mock_api = AsyncMock(spec=RemoteAPI)
        mock_api.get.side_effect = HTTPException(status_code=502, detail="Bad Gateway")
        sep_app.dependency_overrides[get_tasks_api] = lambda: mock_api
        response = test_client.get("/alert-troubleshooting/output/1")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "error" in response.json()
