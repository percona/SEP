"""Define tests for the app.sep.routes.stream_logs module."""

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
            tracking={"allocation_id": "12345", "evaluation_id": "67890"},
        ),
        status=TaskHistoryStatusEnum.SUCCESS,
        task=created_task,
        errors=[],
        anonymized_items=None,
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


async def mock_stream_logs_generator(log_lines):
    """Simulate streaming log lines."""
    for log_line in log_lines:
        yield log_line


def mock_stream(path, task_history_id):
    """Mock stream function for server-sent events."""
    if path == f"/history/{task_history_id}/logs/":
        return mock_stream_logs_generator(
            [
                '{"msg": "log line 1"}',
                '{"msg": "log line 2"}',
            ]
        )
    raise ValueError(f"Unexpected path: {path}")


def test_archives_logs_event_stream(
    test_client, mock_task_api_dep, task_history_response
):
    """Test streaming task history logs as server-sent events."""
    # Use the standalone mock_stream function
    mock_task_api_dep.stream.side_effect = lambda path: mock_stream(
        path, task_history_response.id
    )
    mock_task_api_dep.get.return_value = task_history_response.model_dump()
    response = test_client.get(f"/stream-logs/{task_history_response.id}")

    assert response.status_code == HTTP_200_OK
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

    streamed_content = response.content.decode("utf-8")
    assert "log line 1" in streamed_content
    assert "log line 2" in streamed_content

    mock_task_api_dep.stream.assert_called_once_with(
        f"/history/{task_history_response.id}/logs/"
    )
