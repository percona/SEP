"""Define tests for the app.sep.plugins.alters.routes module."""

from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock

import pytest
from fastapi import status

from app.sep.main import sep_app
from app.sep.plugins.alters.deps import (
    build_alters_task_payload,
    get_alters_index_context,
    get_alters_task,
)
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import (
    TaskHistoryStatusEnum,
    TaskOwner,
)
from tests.app.factories import AltersCreateFactory, TaskFactory


@pytest.fixture
def created_alters() -> AltersCreate:
    """Return a fake created AltersCreate instance."""
    return AltersCreateFactory.build()


@pytest.fixture
def _mock_alters_task_payload(generated_task):
    """Mock the AltersGeneratedTask dependency."""
    sep_app.dependency_overrides[build_alters_task_payload] = lambda: generated_task
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def created_task():
    """Return a fake created Task instance."""
    return TaskFactory.build(owner=TaskOwner.ALTERS)


@pytest.fixture
def _mock_get_alters_task_dep(created_task):
    """Mock the TaskDep dependency."""
    sep_app.dependency_overrides[get_alters_task] = lambda: created_task
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def _mock_get_alters_index_context_dep():
    """Mock the get_alters_index_context dependency with default user context."""
    sep_app.dependency_overrides[get_alters_index_context] = lambda: {
        "user": "default_user"
    }
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_get_alters_index_context_dep")
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
    mock_task_api_dep,
    created_alters,
    generated_task,
):
    """Test creating a new alters task."""
    response = test_client.post(
        "/alters/", data=created_alters.model_dump(), follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/alters"
    mock_task_api_dep.post.assert_any_await(
        "/",
        json=generated_task.model_dump(),
    )


@pytest.mark.usefixtures("_mock_get_alters_task_dep")
def test_alters_detail(
    test_client, created_task, mock_task_api_dep, mock_inventory_api_dep
):
    """Test retrieving an alters' detail page."""
    mock_task_api_dep.get.side_effect = [
        {},  # for /{task.name}/history/
        {},  # for /{task.name}/history/
        {},  # for /stats/{task.name}/
        {"127.0.0.1": "mock_host"},  # for /hosts/
    ]
    mock_data = {
        "TaskGroups": [
            {
                "Tasks": [
                    {
                        "Config": {
                            "command": "pt-online-schema-change",
                            "args": [
                                "--alter=ADD CLOUDM SDF",
                                "P=3666,D=OOOO,t=OPOP",
                                "--recursion-method=none",
                            ],
                        },
                        "Meta": {"schema_name": "OOOO", "table_name": "OPOP"},
                    }
                ]
            }
        ],
        "Constraints": [{"RTarget": "mock_hostname"}],
    }
    created_task.data = mock_data
    response = test_client.get(f"/alters/{created_task.name}?")
    assert response.status_code == status.HTTP_200_OK
    assert created_task.name in response.text
    mock_task_api_dep.get.assert_any_await(f"/{created_task.name}/history/")
    mock_task_api_dep.get.assert_any_await(
        f"/{created_task.name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    mock_task_api_dep.get.assert_any_await(f"/stats/{created_task.name}")


@pytest.mark.usefixtures("_mock_get_alters_task_dep")
def test_alters_execute(
    test_client,
    created_task,
    mock_task_api_dep,
):
    """Test executing a alters task."""
    mock_task_api_dep.post.return_value = AsyncMock()
    eta = datetime.now(tz=UTC) + timedelta(days=1)
    response = test_client.post(
        f"/alters/{created_task.name}", data={"eta": str(eta)}, follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/alters"


@pytest.mark.usefixtures("_mock_get_alters_task_dep")
def test_alters_delete(
    test_client,
    created_task,
    mock_task_api_dep,
):
    """Test deleting a alters task."""
    mock_task_api_dep.delete.return_value = AsyncMock()

    response = test_client.post(
        f"/alters/{created_task.name}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/alters"
    mock_task_api_dep.delete.assert_awaited_once_with(f"/{created_task.name}")
