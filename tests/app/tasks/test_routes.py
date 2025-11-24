"""Define test cases for the task routes in the FastAPI application."""

import pytest
import pytest_asyncio
from fastapi import status

from app.tasks.crud import TaskManager
from app.tasks.deps import get_executor
from app.tasks.main import tasks_app
from app.tasks.models import Task, TaskWrite
from tests.app.factories import TaskFactory


@pytest_asyncio.fixture
async def created_task(session) -> Task:
    """Return a fake created task saved in the database."""
    return await TaskManager.create(
        session,
        TaskWrite.model_validate(TaskFactory.build(name="test-task")),
    )


@pytest.mark.asyncio
async def test_list_tasks_only_returns_active(test_client, session, created_task):
    """Test that listing tasks only returns active (non-deleted) tasks."""
    response = test_client.get("/")
    assert response.status_code == status.HTTP_200_OK
    assert [task["name"] for task in response.json()] == [created_task.name]

    await TaskManager.delete_by_name(session, created_task.name)

    response = test_client.get("/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_task_active_and_get_task_deleted_404(
    test_client, session, created_task
):
    """Test that retrieving an active task works and a deleted task returns 404."""
    response = test_client.get(f"/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    task_data = response.json()
    assert "name" in task_data
    assert task_data["name"] == created_task.name

    await TaskManager.delete_by_name(session, created_task.name)

    response = test_client.get("/baz")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_task_success_and_cannot_delete_twice(
    mocker, test_client, created_task
):
    """Test that deleting a task works and cannot be deleted twice."""
    mocker.patch("app.tasks.routes.PeriodicTaskManager.delete_where", return_value=True)
    response = test_client.delete(f"/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    task_data = response.json()
    assert "name" in task_data
    assert task_data["name"] == created_task.name

    response = test_client.delete(f"/{created_task.name}")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_task_forbidden_when_protected(test_client, session):
    """Test that deleting a protected task returns 403 Forbidden."""
    task_name = "protected-task"
    await TaskManager.create(
        session,
        TaskWrite.model_validate(TaskFactory.build(name=task_name, protected=True)),
    )

    resp = test_client.delete(f"/{task_name}")
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_create_nomad_variable_generates_path(mocker, test_client):
    """Ensure Nomad variable endpoint creates a path and forwards data."""
    mock_executor = mocker.Mock()
    tasks_app.dependency_overrides[get_executor] = lambda *_, **__: mock_executor
    mock_executor.create_nomad_variable.return_value = {}
    try:
        response = test_client.post(
            "/nomad/variables/",
            json={"prefix": "sep/mum", "data": {"config": "secret"}},
        )
    finally:
        tasks_app.dependency_overrides.pop(get_executor, None)

    assert response.status_code == status.HTTP_201_CREATED
    path = response.json()["path"]
    assert path.startswith("sep/mum/")
    mock_executor.create_nomad_variable.assert_called_once()
    kwargs = mock_executor.create_nomad_variable.call_args.kwargs
    assert kwargs["path"] == path
    assert kwargs["data"] == {"config": "secret"}


@pytest.mark.asyncio
async def test_create_nomad_variable_respects_custom_path(mocker, test_client):
    """Verify that providing an explicit path bypasses prefix logic."""
    mock_executor = mocker.Mock()
    tasks_app.dependency_overrides[get_executor] = lambda *_, **__: mock_executor
    mock_executor.create_nomad_variable.return_value = {}
    try:
        response = test_client.post(
            "/nomad/variables/",
            json={"path": "custom/path", "data": {"key": "value"}, "namespace": "foo"},
        )
    finally:
        tasks_app.dependency_overrides.pop(get_executor, None)

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json() == {"path": "custom/path"}
    mock_executor.create_nomad_variable.assert_called_once_with(
        path="custom/path",
        data={"key": "value"},
        namespace="foo",
    )


@pytest.mark.asyncio
async def test_delete_nomad_variable_endpoint(mocker, test_client):
    """Deleting a Nomad variable should call the executor helper."""
    mock_executor = mocker.Mock()
    tasks_app.dependency_overrides[get_executor] = lambda *_, **__: mock_executor
    try:
        response = test_client.delete("/nomad/variables/foo/bar?namespace=ns")
    finally:
        tasks_app.dependency_overrides.pop(get_executor, None)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_executor.delete_nomad_variable.assert_called_once_with(
        path="foo/bar",
        namespace="ns",
    )
