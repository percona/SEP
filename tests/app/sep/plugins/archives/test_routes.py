"""Define tests for the app.sep.plugins.archives.routes module."""

from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import status

from app.core.requests import RemoteAPI
from app.sep.deps import (
    get_tasks_api,
)
from app.sep.main import sep_app
from app.sep.plugins.archives.deps import (
    build_archives_task_payload,
    get_archives_index_context,
    get_archives_task,
)
from app.sep.plugins.archives.models import ArchivesCreate, SwapDropEnum
from app.tasks.models import (
    GeneratedTask,
    Task,
    TaskHistoryStatusEnum,
)
from tests.app.factories import GeneratedTaskFactory, TaskFactory


@pytest.fixture
def mock_task_api() -> AsyncMock:
    """Mock the TaskAPI dependency."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def generated_task() -> GeneratedTask:
    """Return a fake created task."""
    return GeneratedTaskFactory.build()


@pytest.fixture
def created_archives() -> ArchivesCreate:
    """Return a fake created task."""
    return ArchivesCreate(
        alias="drop_swap",
        hostname="source_db",
        service_id=1,
        source_db_id=10,
        source_table_id=20,
        swap_drop=SwapDropEnum.SWAP_DROP,
    )


@pytest.fixture
def created_task() -> Task:
    """Return a fake created task."""
    return TaskFactory.build()


@pytest.fixture
def _mock_task_dep(created_task):
    """Mock the TaskDep dependency."""
    sep_app.dependency_overrides[get_archives_task] = lambda: created_task
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def _mock_archives_index_dep():
    """Mock the TaskDep dependency."""
    sep_app.dependency_overrides[get_archives_index_context] = lambda: {
        "user": "default_user"
    }
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def _mock_archives_task_payload(generated_task):
    """Mock the TaskDep dependency."""
    sep_app.dependency_overrides[build_archives_task_payload] = lambda: generated_task
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_archives_index_dep")
def test_archives_index(
    test_client,
):
    """Test listing archives tasks."""
    response = test_client.get("/archives/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"


@pytest.mark.usefixtures("_mock_archives_task_payload")
def test_archives_create(
    test_client,
    mock_task_api,
    created_archives,
    generated_task,
):
    """Test creating a new archives task."""
    response = test_client.post(
        "/archives/", data=created_archives.model_dump(), follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/archives"
    mock_task_api.post.assert_any_await(
        "/",
        json=generated_task.model_dump(),
    )


@pytest.mark.usefixtures("_mock_task_dep")
def test_archives_detail(
    test_client,
    created_task,
    mock_task_api,
):
    """Test retrieving a archives's detail page."""
    mock_meta_config = yaml.dump(
        {
            "PURGE_LIST": [
                {
                    "SOURCE_DB": "mock_source_db",
                    "SOURCE_TABLE": "mock_source_table",
                    "SWAP_DROP": 1,
                }
            ]
        }
    )

    mock_data = {
        "meta": {
            "config": mock_meta_config,
            "target": "mock_target",
        }
    }
    created_task.data = mock_data
    response = test_client.get(f"/archives/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    assert created_task.name in response.text
    mock_task_api.get.assert_any_await(f"/{created_task.name}/history/")
    mock_task_api.get.assert_any_await(
        f"/{created_task.name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    mock_task_api.get.assert_any_await(f"/stats/{created_task.name}")


@pytest.mark.usefixtures("_mock_task_dep")
def test_archives_execute(
    test_client,
    created_task,
    mock_task_api,
):
    """Test executing a archives task."""
    mock_task_api.post.return_value = AsyncMock()
    eta = datetime.now(tz=UTC) + timedelta(days=1)
    response = test_client.post(
        f"/archives/{created_task.name}", data={"eta": eta}, follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/archives"


@pytest.mark.usefixtures("_mock_task_dep")
def test_archives_delete(
    test_client,
    created_task,
    mock_task_api,
):
    """Test deleting a archives task."""
    mock_task_api.delete.return_value = AsyncMock()

    response = test_client.post(
        f"/archives/{created_task.name}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/archives"
    mock_task_api.delete.assert_awaited_once_with(f"/{created_task.name}")
