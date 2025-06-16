"""Define tests for the app.sep.routes.task_logs module."""

from unittest.mock import AsyncMock

import pytest
from starlette.status import HTTP_200_OK

from app.core.requests import RemoteAPI
from app.sep.deps import get_task_history, get_tasks_api
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
    """Return a valid TaskHistoryResponse object."""
    started_at = faker.past_datetime(start_date="-15d")
    return TaskHistoryResponse(
        id=faker.random_int(min=1),
        execution_request=TaskExecutionRequest(
            task="example-task",
            target="example-target",
            meta={"key": "value"},
            tracking={
                "allocation_id": "12345",
                "evaluation_id": "67890",
                "task_logs": {
                    "run-script": {
                        "stdout": "Success",
                        "stdout_last_offset": 7,
                        "stderr": "",
                        "stderr_last_offset": 0,
                    },
                    "clean-up": {
                        "stdout": "",
                        "stdout_last_offset": 0,
                        "stderr": "",
                        "stderr_last_offset": 0,
                    },
                    "prepare-env": {
                        "stdout": "Warning",
                        "stdout_last_offset": 0,
                        "stderr": "",
                        "stderr_last_offset": 7,
                    },
                },
            },
        ),
        status=TaskHistoryStatusEnum.SUCCESS,
        task=created_task,
        errors=[],
        started_at=started_at,
        finished_at=started_at + faker.time_delta(end_datetime="+1h"),
    )


@pytest.fixture
def mock_task_api_dep(task_history_response):
    """Mock the TaskAPI dependency."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    sep_app.dependency_overrides[get_task_history] = lambda: task_history_response
    yield mock
    sep_app.dependency_overrides = {}


def test_task_logs(test_client, mock_task_api_dep, task_history_response):
    """Test retrieving task logs and status from the task logs endpoint."""
    mock_task_api_dep.post.side_effect = task_history_response
    response = test_client.post(f"/task-logs/{task_history_response.id}")
    assert response.status_code == HTTP_200_OK
    assert response.headers["content-type"] == "application/json"

    data = response.json()
    assert set(data.keys()) == {"task_logs", "status"}

    expected_logs = task_history_response.execution_request.tracking["task_logs"]
    assert data["task_logs"] == expected_logs
    assert data["status"] == task_history_response.status
