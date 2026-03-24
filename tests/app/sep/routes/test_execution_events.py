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

"""Tests for the SEP execution-events proxy route."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.status import HTTP_200_OK

from app.core.requests import RemoteAPI
from app.sep.deps import get_current_user, get_task_history, get_tasks_api
from app.sep.main import sep_app
from app.tasks.models import (
    Task,
    TaskExecutionRequest,
    TaskHistoryResponse,
    TaskHistoryStatusEnum,
)
from tests.app.factories import TaskFactory


@pytest.fixture
def created_task() -> Task:
    """Return a fake created task."""
    return TaskFactory.build()


@pytest.fixture
def task_history_response(faker, created_task):
    """Return a fake task history response."""
    started_at = faker.past_datetime(start_date="-15d")
    return TaskHistoryResponse(
        id=faker.random_int(min=1),
        execution_request=TaskExecutionRequest(
            task="example-task",
            target="example-target",
            meta={"key": "value"},
            tracking={"allocation_id": "12345", "evaluation_id": "67890"},
        ),
        status=TaskHistoryStatusEnum.SUCCESS,
        task=created_task,
        started_at=started_at,
        finished_at=started_at + faker.time_delta(end_datetime="+1h"),
        executed_by=None,
    )


@pytest.fixture
def mock_tasks_api_dep(task_history_response):
    """Override the TaskAPI dependency with an AsyncMock."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    sep_app.dependency_overrides[get_task_history] = lambda: task_history_response
    sep_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        access_token="test-token"
    )
    yield mock
    sep_app.dependency_overrides = {}


class TestListTaskExecutionEvents:
    """Test the list_task_execution_events endpoint."""

    def test_proxies_tasks_api(
        self, test_client, mock_tasks_api_dep, task_history_response
    ):
        """Assert GET /execution-events/{id} forwards to the Tasks API."""
        mock_tasks_api_dep.get.return_value = [
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "type": "Started",
                "description": "Task received",
            },
        ]

        response = test_client.get(f"/execution-events/{task_history_response.id}")

        assert response.status_code == HTTP_200_OK
        body = response.json()
        assert len(body) == 1
        assert body[0]["type"] == "Started"
        assert body[0]["description"] == "Task received"
        assert "timestamp" in body[0]
        mock_tasks_api_dep.get.assert_awaited_once_with(
            f"/history/{task_history_response.id}/events"
        )
