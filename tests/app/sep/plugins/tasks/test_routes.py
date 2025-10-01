"""Define tests for the app.sep.plugins.tasks.routes module."""

from unittest.mock import AsyncMock

import pytest
from fastapi import status

from app.sep.deps import (
    get_task_by_name,
    get_username_mapping,
)
from app.sep.main import sep_app
from app.tasks.models import Task, TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner
from tests.app.factories import TaskFactory


@pytest.fixture
def created_task() -> Task:
    """Return a fake created task."""
    return TaskFactory.build()


@pytest.fixture
def _mock_task_dep(created_task):
    """Mock the TaskDep dependency."""
    sep_app.dependency_overrides[get_task_by_name] = lambda: created_task
    sep_app.dependency_overrides[get_username_mapping] = lambda: {
        "12345678-1234-5678-9abc-123456789012": "test-user"
    }
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
        [created_task.model_dump()],  # for /
        [],  # for /history/
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
def test_task_create(
    test_client,
    mock_task_api_dep,
):
    """Test creating a new task."""
    transform_return = {"transformed": "data"}
    mock_task_api_dep.post.side_effect = [
        transform_return,  # for /transform/
        {"created": "task"},  # for /
    ]

    transform_data = {
        "payload": "fake-payload",
        "fmt": "hcl",
    }

    task_data = {
        "name": "new-task",
        "backend": TaskBackendEnum.NOMAD,
        "owner": TaskOwner.ANY,
        "alert_on_fail": False,
    }

    form_data = transform_data | task_data

    response = test_client.post("/tasks/", data=form_data, follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/tasks/{task_data['name']}"
    )
    mock_task_api_dep.post.assert_any_await(
        "/transform/", json=transform_data, params={"backend": TaskBackendEnum.NOMAD}
    )
    mock_task_api_dep.post.assert_awaited_with(
        "/", json=task_data | {"data": transform_return}
    )


@pytest.mark.usefixtures("_mock_task_dep")
def test_task_detail(
    test_client,
    created_task,
    mock_task_api_dep,
):
    """Test retrieving a task's detail page."""
    mock_task_api_dep.get.return_value = []
    mock_task_api_dep.get.side_effect = [
        [],  # for /{task_name}/periodic/
        [],  # for /{task_name}/history/
        [],  # for /{task_name}/history/?status=RUNNING
        {"address1": "host1", "address2": "host2"},  # for /hosts/
    ]

    response = test_client.get(f"/tasks/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    assert created_task.name in response.text
    mock_task_api_dep.get.assert_any_await(f"/{created_task.name}/periodic/")
    mock_task_api_dep.get.assert_any_await(f"/{created_task.name}/history/")
    mock_task_api_dep.get.assert_any_await(
        f"/{created_task.name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    mock_task_api_dep.get.assert_awaited_with("/hosts/")


@pytest.mark.usefixtures("_mock_task_dep")
def test_task_execute(
    test_client,
    created_task,
    mock_task_api_dep,
):
    """Test executing a task."""
    mock_task_api_dep.post.return_value = AsyncMock()

    execute_data = {
        "meta": {},
        "payload": None,
        "eta": None,
        "anonymize_mask": None,
    }

    response = test_client.post(f"/tasks/{created_task.name}", follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/tasks/{created_task.name}"
    )
    mock_task_api_dep.post.assert_awaited_once_with(
        f"/execute/{created_task.name}", json=execute_data
    )


@pytest.mark.usefixtures("_mock_task_dep")
def test_tasks_delete(
    test_client,
    created_task,
    mock_task_api_dep,
):
    """Test deleting a task."""
    mock_task_api_dep.delete.return_value = AsyncMock()

    response = test_client.post(
        f"/tasks/{created_task.name}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/tasks"
    mock_task_api_dep.delete.assert_awaited_once_with(f"/{created_task.name}")
