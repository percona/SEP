"""Define tests for the app.sep.routes.download_files module."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.status import HTTP_200_OK

from app.core.requests import RemoteAPI
from app.sep.deps import (
    get_current_user,
    get_task_history,
    get_tasks_api,
    get_tasks_client,
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
        status=TaskHistoryStatusEnum.SUCCESS,
        task=created_task,
        started_at=started_at,
        finished_at=started_at + faker.time_delta(end_datetime="+1h"),
        executed_by=None,
    )


async def _mock_file_stream(chunks):
    """Yield byte chunks for mocking file streams."""
    for chunk in chunks:
        yield chunk


@pytest.fixture
def mock_tasks_api_dep(task_history_response):
    """Override the TaskAPI dependency with an AsyncMock."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    sep_app.dependency_overrides[get_task_history] = lambda: task_history_response
    sep_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        access_token="test-token"
    )
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_tasks_client_dep(task_history_response):
    """Override the TasksClient dependency with a mock that provides auth context."""
    client = AsyncMock(spec=RemoteAPI)

    @contextmanager
    def auth(token):
        yield client

    client.auth = auth
    sep_app.dependency_overrides[get_tasks_client] = lambda: client
    sep_app.dependency_overrides[get_task_history] = lambda: task_history_response
    sep_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        access_token="test-token"
    )
    yield client
    sep_app.dependency_overrides = {}


# ---------------------------------------------------------------------------
# list_task_history_files
# ---------------------------------------------------------------------------


class TestListTaskHistoryFiles:
    """Test the list_task_history_files endpoint."""

    def test_returns_file_metadata(
        self, test_client, mock_tasks_api_dep, task_history_response
    ):
        """Assert the endpoint returns file metadata from the tasks API."""
        expected_files = {
            "output.log": {"size": 1024, "is_dir": False},
            "data/": {"size": 0, "is_dir": True},
        }
        mock_tasks_api_dep.get.return_value = expected_files

        response = test_client.get(f"/files/{task_history_response.id}")

        assert response.status_code == HTTP_200_OK
        assert response.json() == expected_files
        mock_tasks_api_dep.get.assert_awaited_once_with(
            f"/history/{task_history_response.id}/files/"
        )


# ---------------------------------------------------------------------------
# download_task_history_file
# ---------------------------------------------------------------------------


class TestDownloadTaskHistoryFile:
    """Test the download_task_history_file endpoint."""

    def test_streams_file_with_correct_headers(
        self, test_client, mock_tasks_client_dep, task_history_response
    ):
        """Assert file download streams with correct Content-Disposition."""
        mock_tasks_client_dep.get.return_value = {
            "backup.sql": {"size": 2048, "is_dir": False}
        }
        mock_tasks_client_dep.stream.return_value = _mock_file_stream(
            [b"chunk1", b"chunk2"]
        )

        response = test_client.get(
            f"/files/{task_history_response.id}/download?path=backup.sql"
        )

        assert response.status_code == HTTP_200_OK
        assert response.headers["content-disposition"] == (
            'attachment; filename="backup.sql"'
        )
        assert response.content == b"chunk1chunk2"

    def test_directory_path_triggers_tar_gz(
        self, test_client, mock_tasks_client_dep, task_history_response
    ):
        """Assert directory downloads use .tar.gz filename suffix."""
        mock_tasks_client_dep.get.return_value = {"data/": {"size": 0, "is_dir": True}}
        mock_tasks_client_dep.stream.return_value = _mock_file_stream([b"tardata"])

        response = test_client.get(
            f"/files/{task_history_response.id}/download?path=data/"
        )

        assert response.status_code == HTTP_200_OK
        assert response.headers["content-disposition"] == (
            'attachment; filename="data.tar.gz"'
        )

    def test_metadata_error_still_streams(
        self, test_client, mock_tasks_client_dep, task_history_response
    ):
        """Assert file still streams when metadata fetch raises HTTPException."""
        from fastapi import HTTPException

        mock_tasks_client_dep.get.side_effect = HTTPException(status_code=500)
        mock_tasks_client_dep.stream.return_value = _mock_file_stream(
            [b"fallback-data"]
        )

        response = test_client.get(
            f"/files/{task_history_response.id}/download?path=unknown.bin"
        )

        assert response.status_code == HTTP_200_OK
        assert response.headers["content-disposition"] == (
            'attachment; filename="unknown.bin"'
        )
        assert response.content == b"fallback-data"

    def test_no_path_streams_without_headers(
        self, test_client, mock_tasks_client_dep, task_history_response
    ):
        """Assert download without path query param streams without Content-Disposition."""
        mock_tasks_client_dep.stream.return_value = _mock_file_stream([b"raw-data"])

        response = test_client.get(f"/files/{task_history_response.id}/download")

        assert response.status_code == HTTP_200_OK
        assert "content-disposition" not in response.headers
