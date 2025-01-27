"""Define tests for the app.sep.plugins.alters.routes module."""

from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock

import pytest
from fastapi import status

from app.core.requests import RemoteAPI
from app.sep.deps import (
    get_tasks_api,
)
from app.sep.main import sep_app
from app.sep.plugins.alters.deps import (
    build_alters_task_payload,
    get_alters_index_context,
    get_alters_task,
)
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import (
    GeneratedTask,
    Task,
    TaskHistoryStatusEnum,
)
from tests.app.factories import AltersCreateFactory, GeneratedTaskFactory, TaskFactory


@pytest.fixture
def mock_task_api() -> AsyncMock:
    """Mock the TaskAPI dependency."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def generated_task() -> GeneratedTask:
    """Return a fake generated task while creating alters."""
    return GeneratedTaskFactory.build()


@pytest.fixture
def created_alters() -> AltersCreate:
    """Return a fake created AltersCreate instance."""
    return AltersCreateFactory.build()


@pytest.fixture
def created_task() -> Task:
    """Return a fake created task."""
    return TaskFactory.build()


@pytest.fixture
def _mock_task_dep(created_task):
    """Mock the TaskDep dependency."""
    sep_app.dependency_overrides[get_alters_task] = lambda: created_task
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def _mock_alters_index_dep():
    """Mock the get_alters_index_context dependency with default user context."""
    sep_app.dependency_overrides[get_alters_index_context] = lambda: {
        "user": "default_user"
    }
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def _mock_alters_task_payload(generated_task):
    """Mock the AltersGeneratedTask dependency."""
    sep_app.dependency_overrides[build_alters_task_payload] = lambda: generated_task
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_alters_index_dep")
def test_alters_index(
    test_client,
):
    """Test listing alters tasks."""
    response = test_client.get("/alters/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"


@pytest.mark.usefixtures("_mock_alters_task_payload")
def test_alters_create(
    test_client,
    mock_task_api,
    created_alters,
    generated_task,
):
    """Test creating a new alters task."""
    response = test_client.post(
        "/alters/", data=created_alters.model_dump(), follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/alters"
    mock_task_api.post.assert_any_await(
        "/generate/",
        json=generated_task.model_dump(),
    )


@pytest.mark.usefixtures("_mock_task_dep")
def test_alters_detail(
    test_client,
    created_task,
    mock_task_api,
):
    """Test retrieving a alters's detail page."""
    mock_data = {
        "TaskGroups": [
            {
                "Tasks": [
                    {
                        "Config": {
                            "command": "echo",
                            "args": ["hello", "world"],
                        },
                        "Meta": {
                            "schema_name": "public",
                            "table_name": "example_table",
                        },
                    }
                ]
            }
        ],
        "Constraints": [{"RTarget": "mock_hostname"}],
    }
    created_task.data = mock_data
    response = test_client.get(f"/alters/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    assert created_task.name in response.text
    mock_task_api.get.assert_any_await(f"/{created_task.name}/history/")
    mock_task_api.get.assert_any_await(
        f"/{created_task.name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    mock_task_api.get.assert_any_await(f"/stats/{created_task.name}")


@pytest.mark.usefixtures("_mock_task_dep")
def test_alters_execute(
    test_client,
    created_task,
    mock_task_api,
):
    """Test executing a alters task."""
    mock_task_api.post.return_value = AsyncMock()
    eta = datetime.now(tz=UTC) + timedelta(days=1)
    response = test_client.post(
        f"/alters/{created_task.name}", data={"eta": eta}, follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/alters"


@pytest.mark.usefixtures("_mock_task_dep")
def test_alters_delete(
    test_client,
    created_task,
    mock_task_api,
):
    """Test deleting a alters task."""
    mock_task_api.delete.return_value = AsyncMock()

    response = test_client.post(
        f"/alters/{created_task.name}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/alters"
    mock_task_api.delete.assert_awaited_once_with(f"/{created_task.name}")
