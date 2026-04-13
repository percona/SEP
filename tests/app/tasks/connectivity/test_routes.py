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

"""Test the connectivity check route endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.api.deps import get_current_user
from app.tasks.connectivity.models import (
    ConnectivityCheckResponse,
    ConnectivityServiceType,
)
from app.tasks.deps import get_executor, get_session
from app.tasks.execution.models import BaseExecutor
from app.tasks.main import tasks_app
from app.tasks.models import Task

MOCK_TASK_HISTORY_ID = 42


@pytest.fixture
def mock_executor() -> MagicMock:
    """Return a mock executor with node1 available."""
    executor = MagicMock(spec=BaseExecutor)
    executor.get_hosts = MagicMock(return_value={"node1": "10.0.0.1"})
    return executor


@pytest.fixture
def test_client(regular_user, mock_executor) -> TestClient:
    """Create an authenticated test client for the Tasks API."""
    session = AsyncMock()
    tasks_app.dependency_overrides[get_current_user] = lambda: regular_user
    tasks_app.dependency_overrides[get_session] = lambda: session
    tasks_app.dependency_overrides[get_executor] = lambda: mock_executor
    yield TestClient(tasks_app)
    tasks_app.dependency_overrides = {}


class TestConnectivityCheckEndpoint:
    """Test POST /connectivity-check/ endpoint."""

    def test_success(self, test_client, mock_executor):
        """Verify successful connectivity check returns 200."""
        mock_task = MagicMock(spec=Task)
        mock_task.id = 1
        mock_task.name = "run-python"
        expected_response = ConnectivityCheckResponse(
            success=True, error=None, task_history_id=MOCK_TASK_HISTORY_ID
        )

        with (
            patch(
                "app.tasks.connectivity.routes.TaskManager.retrieve_by_name",
                new=AsyncMock(return_value=mock_task),
            ),
            patch(
                "app.tasks.connectivity.routes.get_executor_for_task",
                return_value=mock_executor,
            ),
            patch(
                "app.tasks.connectivity.routes.check_connectivity",
                new=AsyncMock(return_value=expected_response),
            ),
        ):
            response = test_client.post(
                "/connectivity-check/",
                json={
                    "target": "node1",
                    "host": "db-host",
                    "port": 3306,
                    "service_type": ConnectivityServiceType.MYSQL.value,
                },
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["task_history_id"] == MOCK_TASK_HISTORY_ID

    def test_invalid_target_returns_400(self, test_client, mock_executor):
        """Verify 400 when target is not in available Nomad hosts."""
        mock_task = MagicMock(spec=Task)
        mock_task.id = 1
        mock_task.name = "run-python"

        with (
            patch(
                "app.tasks.connectivity.routes.TaskManager.retrieve_by_name",
                new=AsyncMock(return_value=mock_task),
            ),
            patch(
                "app.tasks.connectivity.routes.get_executor_for_task",
                return_value=mock_executor,
            ),
        ):
            response = test_client.post(
                "/connectivity-check/",
                json={
                    "target": "unknown-node",
                    "host": "db-host",
                    "port": 3306,
                    "service_type": ConnectivityServiceType.MYSQL.value,
                },
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_service_type_returns_422(self, test_client):
        """Verify 422 when an unsupported service_type is provided."""
        response = test_client.post(
            "/connectivity-check/",
            json={
                "target": "node1",
                "host": "db-host",
                "port": 3306,
                "service_type": "REDIS",
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_invalid_timeout_returns_422(self, test_client):
        """Verify 422 when timeout exceeds the maximum."""
        response = test_client.post(
            "/connectivity-check/",
            json={
                "target": "node1",
                "host": "db-host",
                "port": 3306,
                "service_type": ConnectivityServiceType.MYSQL.value,
                "timeout": 120,
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_zero_timeout_returns_422(self, test_client):
        """Verify 422 when timeout is zero."""
        response = test_client.post(
            "/connectivity-check/",
            json={
                "target": "node1",
                "host": "db-host",
                "port": 3306,
                "service_type": ConnectivityServiceType.MYSQL.value,
                "timeout": 0,
            },
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_unauthenticated_returns_401(self):
        """Verify 401 when no authentication is provided."""
        tasks_app.dependency_overrides = {}
        client = TestClient(tasks_app, raise_server_exceptions=False)
        response = client.post(
            "/connectivity-check/",
            json={
                "target": "node1",
                "host": "db-host",
                "port": 3306,
                "service_type": ConnectivityServiceType.MYSQL.value,
            },
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
