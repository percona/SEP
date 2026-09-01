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

"""Tests for the SEP dashboard stats JSON API route at ``/api/sep/dashboard/``."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.sep.api.constants import UPSTREAM_ERROR_HEADER
from app.sep.deps import get_session
from app.sep.main import sep_app


@pytest.fixture
def mock_session_dep() -> Iterator[AsyncMock]:
    """Override ``get_session`` with a bare AsyncMock for dashboard tests."""
    mock = AsyncMock(spec=AsyncSession)
    sep_app.dependency_overrides[get_session] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


class TestDashboardStatsEndpoint:
    """Tests for ``GET /api/sep/dashboard/`` happy-path and degradation cases."""

    def test_returns_all_counts_no_error_header(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_session_dep: AsyncMock,
        mocker,
    ) -> None:
        """Return all counts and omit the error header on happy path."""
        mocker.patch(
            "app.sep.api.routes.dashboard.SnippetManager.count",
            new=AsyncMock(return_value=23),
        )
        mock_inventory_api_dep.get.return_value = {
            "nodes": 42,
            "services": 5,
            "schemas": 3,
            "tables": 100,
        }
        mock_task_api_dep.get.side_effect = [
            {"items": [], "total": 7, "offset": 0, "limit": 0},
            [
                {"id": "nomad-1", "name": "host-1", "address": "10.0.0.1"},
                {"id": "nomad-2", "name": "host-2", "address": "10.0.0.2"},
                {"id": "nomad-3", "name": "host-3", "address": "10.0.0.3"},
            ],
        ]
        response = test_client.get("/api/sep/dashboard/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "nodes": 42,
            "tasks": 7,
            "snippets": 23,
            "targets": 3,
        }
        assert UPSTREAM_ERROR_HEADER not in response.headers

    def test_inventory_failure_sets_error_header(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_session_dep: AsyncMock,
        mocker,
    ) -> None:
        """Set the error header and return ``nodes=0`` when Inventory API fails."""
        mocker.patch(
            "app.sep.api.routes.dashboard.SnippetManager.count",
            new=AsyncMock(return_value=5),
        )
        mock_inventory_api_dep.get.side_effect = HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="inventory unreachable"
        )
        mock_task_api_dep.get.side_effect = [
            {"items": [], "total": 3, "offset": 0, "limit": 0},
            [],
        ]
        response = test_client.get("/api/sep/dashboard/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["nodes"] == 0
        assert data["tasks"] == 3  # noqa: PLR2004 — fixture value
        assert data["snippets"] == 5  # noqa: PLR2004 — fixture value
        assert response.headers[UPSTREAM_ERROR_HEADER] == "nodes"

    def test_inventory_none_response_sets_error_header(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_session_dep: AsyncMock,
        mocker,
    ) -> None:
        """Set the error header when Inventory API returns None (HTTP 204)."""
        mocker.patch(
            "app.sep.api.routes.dashboard.SnippetManager.count",
            new=AsyncMock(return_value=0),
        )
        mock_inventory_api_dep.get.return_value = None
        mock_task_api_dep.get.side_effect = [
            {"items": [], "total": 0, "offset": 0, "limit": 0},
            [],
        ]
        response = test_client.get("/api/sep/dashboard/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["nodes"] == 0
        assert response.headers[UPSTREAM_ERROR_HEADER] == "nodes"

    def test_tasks_api_failure_sets_error_header(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_session_dep: AsyncMock,
        mocker,
    ) -> None:
        """Set the error header for tasks and targets when the Tasks API is down."""
        mocker.patch(
            "app.sep.api.routes.dashboard.SnippetManager.count",
            new=AsyncMock(return_value=10),
        )
        mock_inventory_api_dep.get.return_value = {"nodes": 8}
        mock_task_api_dep.get.side_effect = OSError("tasks unreachable")
        response = test_client.get("/api/sep/dashboard/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tasks"] == 0
        assert data["targets"] == 0
        assert data["nodes"] == 8  # noqa: PLR2004 — fixture value
        assert data["snippets"] == 10  # noqa: PLR2004 — fixture value
        assert response.headers[UPSTREAM_ERROR_HEADER] == "tasks,targets"

    def test_snippet_db_failure_sets_error_header(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_session_dep: AsyncMock,
        mocker,
    ) -> None:
        """Set the error header for snippets when the database query fails."""
        mocker.patch(
            "app.sep.api.routes.dashboard.SnippetManager.count",
            new=AsyncMock(side_effect=Exception("db error")),
        )
        mock_inventory_api_dep.get.return_value = {"nodes": 4}
        mock_task_api_dep.get.side_effect = [
            {"items": [], "total": 2, "offset": 0, "limit": 0},
            [{"id": "nomad-1", "name": "n1", "address": "10.0.0.1"}],
        ]
        response = test_client.get("/api/sep/dashboard/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["snippets"] == 0
        assert data["nodes"] == 4  # noqa: PLR2004 — fixture value
        assert data["tasks"] == 2  # noqa: PLR2004 — fixture value
        assert data["targets"] == 1
        assert response.headers[UPSTREAM_ERROR_HEADER] == "snippets"

    def test_all_sources_healthy_returns_real_zeroes(
        self,
        test_client: TestClient,
        mock_task_api_dep: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_session_dep: AsyncMock,
        mocker,
    ) -> None:
        """Return all-zero counts with no error header when sources are healthy but empty."""
        mocker.patch(
            "app.sep.api.routes.dashboard.SnippetManager.count",
            new=AsyncMock(return_value=0),
        )
        mock_inventory_api_dep.get.return_value = {"nodes": 0}
        mock_task_api_dep.get.side_effect = [
            {"items": [], "total": 0, "offset": 0, "limit": 0},
            [],
        ]
        response = test_client.get("/api/sep/dashboard/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"nodes": 0, "tasks": 0, "snippets": 0, "targets": 0}
        assert UPSTREAM_ERROR_HEADER not in response.headers


class TestDashboardStatsAuth:
    """Tests for ``/api/sep/dashboard/`` authentication enforcement."""

    @pytest.fixture
    def unauthenticated_client(self) -> Iterator[TestClient]:
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
            "/api/sep/dashboard/", follow_redirects=False
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()
