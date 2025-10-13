"""Define tests for the app.sep.routes.stream_logs module."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.status import HTTP_200_OK

from app.core.requests import RemoteAPI
from app.sep.deps import CurrentUser, get_task_history, get_tasks_client
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


async def mock_stream_logs_generator(log_lines):
    """Mock generator that yields log lines."""
    for log_line in log_lines:
        yield log_line


def mock_stream(path, task_history_id):
    """Mock the stream method of the RemoteAPI client."""
    if path == f"/history/{task_history_id}/logs/":
        return mock_stream_logs_generator(
            [
                b'{"msg": "log line 1"}',
                b'{"msg": "log line 2"}',
            ]
        )
    raise ValueError(f"Unexpected path: {path}")


@pytest.fixture
def mock_tasks_client(task_history_response):
    """Mock the TasksClient dependency returned by get_tasks_client."""
    client = AsyncMock(spec=RemoteAPI)

    @contextmanager
    def auth(token: str):
        yield client

    client.auth = auth
    client.stream.side_effect = lambda path, **_kwargs: mock_stream(
        path, task_history_response.id
    )
    client.get.return_value = task_history_response.model_dump()

    sep_app.dependency_overrides[get_tasks_client] = lambda: client
    sep_app.dependency_overrides[get_task_history] = lambda: task_history_response
    sep_app.dependency_overrides[CurrentUser] = lambda: SimpleNamespace(
        access_token="test-token"
    )

    yield client
    sep_app.dependency_overrides = {}


def test_archives_logs_event_stream(
    mocker, test_client, mock_tasks_client, task_history_response
):
    """Test the /stream-logs/{task_history_id} endpoint for streaming logs."""
    response = test_client.get(f"/stream-logs/{task_history_response.id}")

    assert response.status_code == HTTP_200_OK
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

    streamed_content = response.content.decode("utf-8")
    assert "log line 1" in streamed_content
    assert "log line 2" in streamed_content

    mock_tasks_client.stream.assert_called_once_with(
        f"/history/{task_history_response.id}/logs/",
        params=mocker.ANY,
    )
