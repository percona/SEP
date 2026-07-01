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

"""Define tests for the app.sep.apps.tasks.routes module."""

import pytest
from fastapi import status

from app.sep.deps import get_task_by_name
from app.sep.main import sep_app
from app.tasks.models import (
    Task,
    TaskHistoryStatusEnum,
)
from tests.app.factories import TaskFactory


@pytest.fixture
def created_task() -> Task:
    """Return a fake created task."""
    return TaskFactory.build()


@pytest.fixture
def _mock_task_dep(created_task, mock_get_username_mapping):
    """Mock the TaskDep dependency."""
    sep_app.dependency_overrides[get_task_by_name] = lambda: created_task
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_task_dep")
def test_tasks_list(
    test_client,
    mock_task_api_dep,
    created_task,
):
    """Test listing tasks."""
    mock_task_api_dep.get.side_effect = [
        {
            "items": [created_task.model_dump()],
            "total": 1,
            "offset": 0,
            "limit": 50,
        },  # for /
        {"items": [], "total": 0, "offset": 0, "limit": 50},  # for /history/
    ]
    response = test_client.get("/tasks/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert created_task.name in response.text
    mock_task_api_dep.get.assert_any_await("/")
    mock_task_api_dep.get.assert_awaited_with(
        "/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )


@pytest.mark.usefixtures("_mock_task_dep")
def test_task_detail(
    test_client,
    created_task,
    mock_task_api_dep,
    mock_inventory_api_dep,
):
    """Test retrieving a task's detail page."""
    mock_task_api_dep.get.return_value = []
    mock_task_api_dep.get.side_effect = [
        {"address1": "host1", "address2": "host2"},  # for /hosts/ (dependency)
        {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        },  # for /{task_name}/history/
        {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        },  # for /{task_name}/history/?status=RUNNING
    ]

    response = test_client.get(f"/tasks/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    assert created_task.name in response.text
    assert f"/tasks/{created_task.name}/delete" not in response.text
    assert "new-periodic-task-form" not in response.text
    mock_task_api_dep.get.assert_any_await("/hosts/")
    mock_task_api_dep.get.assert_any_await(f"/{created_task.name}/history/")
    mock_task_api_dep.get.assert_any_await(
        f"/{created_task.name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )


def test_mutating_routes_removed(test_client, created_task):
    """Assert the generic create/execute/delete routes no longer exist.

    The tasks plugin is read-only; creating, running, and deleting a task
    stay on the owning plugins. ``POST /tasks/`` and ``POST /tasks/{name}``
    keep only their ``GET`` handlers (405). ``POST /tasks/{name}/delete`` is
    gone: the old handler 303-redirected to ``/tasks``, so its absence is
    confirmed by the request no longer landing on that location (it falls
    through to the catch-all 404 handler instead).
    """
    assert (
        test_client.post("/tasks/", follow_redirects=False).status_code
        == status.HTTP_405_METHOD_NOT_ALLOWED
    )
    assert (
        test_client.post(
            f"/tasks/{created_task.name}", follow_redirects=False
        ).status_code
        == status.HTTP_405_METHOD_NOT_ALLOWED
    )
    delete_response = test_client.post(
        f"/tasks/{created_task.name}/delete", follow_redirects=False
    )
    assert delete_response.headers.get("location") != "/tasks"
