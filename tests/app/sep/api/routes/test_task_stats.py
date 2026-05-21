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

"""Tests for the SEP task-stats JSON API route at ``/api/sep/task-stats/``."""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.exceptions import HTTPBadGatewayException
from app.sep.main import sep_app

EMPTY_STATS = {
    "engine": "nomad",
    "total": 0,
    "status": {"pass": 0, "fail": 0},
    "duration": {
        "average_seconds": None,
        "last_seconds": None,
        "total_seconds": None,
    },
    "last_finished_at": None,
}


class TestSepTaskStatsEndpoint:
    """Tests for ``GET /api/sep/task-stats/{task_name}`` proxy behavior."""

    def test_returns_upstream_stats_payload(
        self,
        test_client: TestClient,
        mock_task_api_dep,
    ) -> None:
        """Forward the upstream stats payload unchanged on success."""
        payload = {
            "engine": "nomad",
            "total": 3,
            "status": {"pass": 2, "fail": 1},
            "duration": {
                "average_seconds": 12.5,
                "last_seconds": 10.0,
                "total_seconds": 37.5,
            },
            "last_finished_at": "2026-05-21T10:00:00+00:00",
        }
        mock_task_api_dep.get.return_value = payload
        response = test_client.get("/api/sep/task-stats/my-task")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload

    def test_proxies_task_name_to_upstream_path(
        self,
        test_client: TestClient,
        mock_task_api_dep,
    ) -> None:
        """Call ``tasks_api.get('/stats/{task_name}')`` with the URL path param."""
        mock_task_api_dep.get.return_value = {
            "engine": "nomad",
            "total": 0,
            "status": {"pass": 0, "fail": 0},
            "duration": {
                "average_seconds": None,
                "last_seconds": None,
                "total_seconds": None,
            },
            "last_finished_at": None,
        }
        test_client.get("/api/sep/task-stats/some-task-name")
        mock_task_api_dep.get.assert_called_once_with("/stats/some-task-name")

    def test_tasks_failure_returns_empty_stats(
        self,
        test_client: TestClient,
        mock_task_api_dep,
    ) -> None:
        """Return ``200`` empty stats + ``X-Sep-Upstream-Error`` on upstream HTTP failure."""
        mock_task_api_dep.get.side_effect = HTTPBadGatewayException("tasks unreachable")
        response = test_client.get("/api/sep/task-stats/my-task")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == EMPTY_STATS
        assert response.headers["X-Sep-Upstream-Error"] == "tasks unreachable"

    def test_tasks_oserror_returns_empty_stats(
        self,
        test_client: TestClient,
        mock_task_api_dep,
    ) -> None:
        """Return empty stats when the Tasks API raises an OSError."""
        mock_task_api_dep.get.side_effect = OSError("connection refused")
        response = test_client.get("/api/sep/task-stats/my-task")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == EMPTY_STATS
        assert response.headers["X-Sep-Upstream-Error"] == "connection refused"


class TestSepTaskStatsAuth:
    """Tests for ``/api/sep/task-stats/`` authentication enforcement."""

    @pytest.fixture
    def unauthenticated_client(self) -> TestClient:
        """Yield a TestClient with no auth dependency overrides applied."""
        previous = sep_app.dependency_overrides
        sep_app.dependency_overrides = {}
        try:
            yield TestClient(sep_app, raise_server_exceptions=False)
        finally:
            sep_app.dependency_overrides = previous

    def test_unauthenticated_returns_json_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Reject anonymous requests with a JSON 401 response."""
        response = unauthenticated_client.get(
            "/api/sep/task-stats/foo", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()
