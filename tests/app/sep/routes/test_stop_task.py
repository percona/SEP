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

"""Define tests for the app.sep.routes.stop_task module."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.status import HTTP_303_SEE_OTHER

from app.core.requests import RemoteAPI
from app.sep.deps import (
    get_current_user,
    get_task_history,
    get_tasks_api,
    validate_csrf,
)
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
        status=TaskHistoryStatusEnum.RUNNING,
        task=created_task,
        started_at=started_at,
        finished_at=None,
        executed_by=None,
    )


@pytest.fixture
def stop_task_client(regular_user, task_history_response):
    """Create a test client with all stop_task endpoint dependencies overridden."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[validate_csrf] = lambda: True
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    sep_app.dependency_overrides[get_task_history] = lambda: task_history_response

    client = TestClient(sep_app, raise_server_exceptions=False)
    yield client, mock
    sep_app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# stop_task_execution
# ---------------------------------------------------------------------------


class TestStopTaskExecution:
    """Test the stop_task_execution endpoint."""

    def test_stopped_task_shows_success_message(
        self, stop_task_client, task_history_response
    ):
        """Assert STOPPED status produces the correct success message."""
        client, mock_api = stop_task_client
        mock_api.post.return_value = {
            "task": {"name": "my-backup"},
            "status": TaskHistoryStatusEnum.STOPPED,
        }

        response = client.post(
            f"/stop-task/{task_history_response.id}",
            headers={"referer": "/tasks"},
            follow_redirects=False,
        )

        assert response.status_code == HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/tasks"
        mock_api.post.assert_awaited_once_with(
            f"/history/{task_history_response.id}/stop/"
        )

    def test_non_stopped_task_shows_cancelled_message(
        self, stop_task_client, task_history_response
    ):
        """Assert non-STOPPED status produces the cancelled-before-execution message."""
        client, mock_api = stop_task_client
        mock_api.post.return_value = {
            "task": {"name": "my-backup"},
            "status": TaskHistoryStatusEnum.FAILED,
        }

        response = client.post(
            f"/stop-task/{task_history_response.id}",
            headers={"referer": "/tasks"},
            follow_redirects=False,
        )

        assert response.status_code == HTTP_303_SEE_OTHER

    def test_redirects_to_referer(self, stop_task_client, task_history_response):
        """Assert the response redirects to the referer header value."""
        client, mock_api = stop_task_client
        mock_api.post.return_value = {
            "task": {"name": "my-backup"},
            "status": TaskHistoryStatusEnum.STOPPED,
        }

        response = client.post(
            f"/stop-task/{task_history_response.id}",
            headers={"referer": "/custom/page"},
            follow_redirects=False,
        )

        assert response.status_code == HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/custom/page"

    def test_defaults_to_root_when_no_referer(
        self, stop_task_client, task_history_response
    ):
        """Assert the response redirects to / when no referer is provided."""
        client, mock_api = stop_task_client
        mock_api.post.return_value = {
            "task": {"name": "my-backup"},
            "status": TaskHistoryStatusEnum.STOPPED,
        }

        response = client.post(
            f"/stop-task/{task_history_response.id}",
            follow_redirects=False,
        )

        assert response.status_code == HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"
