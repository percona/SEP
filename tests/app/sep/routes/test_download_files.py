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

"""Define tests for the app.sep.routes.download_files module."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aioresponses import aioresponses, CallbackResult
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from app.core.requests import RemoteAPI
from app.sep.deps import (
    get_current_user,
    get_task_history,
    get_tasks_api,
    get_tasks_client,
)
from app.sep.main import sep_app
from tests.app.asgi_stream import asgi_stream
from tests.app.sep.routes.conftest import TASKS_ENDPOINT


async def _mock_file_stream(chunks):
    """Yield byte chunks for mocking file streams."""
    for chunk in chunks:
        yield chunk


async def _mock_failing_file_stream():
    """Yield one chunk then raise, simulating a stream that breaks mid-transfer."""
    yield b"partial-"
    raise RuntimeError("upstream stream broke")


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

    def test_returns_empty_dict_when_tasks_api_returns_400(
        self, test_client, mock_tasks_api_dep, task_history_response
    ):
        """Assert HTTP 400 from the Tasks API (no output_files_path) is returned as {}."""
        mock_tasks_api_dep.get.side_effect = HTTPException(
            status_code=HTTP_400_BAD_REQUEST
        )

        response = test_client.get(f"/files/{task_history_response.id}")

        assert response.status_code == HTTP_200_OK
        assert response.json() == {}

    def test_returns_empty_dict_when_tasks_api_returns_409(
        self, test_client, mock_tasks_api_dep, task_history_response
    ):
        """Assert HTTP 409 (task still running) is returned as {}."""
        mock_tasks_api_dep.get.side_effect = HTTPException(
            status_code=HTTP_409_CONFLICT
        )

        response = test_client.get(f"/files/{task_history_response.id}")

        assert response.status_code == HTTP_200_OK
        assert response.json() == {}

    def test_propagates_other_http_exceptions(
        self,
        mocker,
        test_client,
        regular_user,
        mock_tasks_api_dep,
        task_history_response,
    ):
        """Assert HTTP errors other than 400/409 are re-raised, not silently returned as {}."""
        mock_tasks_api_dep.get.side_effect = HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR
        )

        response = test_client.get(f"/files/{task_history_response.id}")

        assert response.status_code == HTTP_500_INTERNAL_SERVER_ERROR

    def test_returns_empty_dict_when_tasks_api_returns_none(
        self, test_client, mock_tasks_api_dep, task_history_response
    ):
        """Assert a ``None`` response from the Tasks API is normalised to {}."""
        mock_tasks_api_dep.get.return_value = None

        response = test_client.get(f"/files/{task_history_response.id}")

        assert response.status_code == HTTP_200_OK
        assert response.json() == {}


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
        mock_tasks_client_dep.stream_chunks.return_value = _mock_file_stream(
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
        mock_tasks_client_dep.stream_chunks.return_value = _mock_file_stream(
            [b"tardata"]
        )

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
        mock_tasks_client_dep.get.side_effect = HTTPException(status_code=500)
        mock_tasks_client_dep.stream_chunks.return_value = _mock_file_stream(
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

    def test_stream_failure_after_headers(
        self, test_client, mock_tasks_client_dep, task_history_response
    ):
        """Assert a stream that breaks mid-transfer delivers the partial download.

        The download headers (200, Content-Disposition) are committed before the
        first chunk, so a later upstream failure cannot change the status code; the
        client receives the bytes produced before the break.
        """
        mock_tasks_client_dep.get.return_value = {
            "backup.sql": {"size": 2048, "is_dir": False}
        }
        mock_tasks_client_dep.stream_chunks.return_value = _mock_failing_file_stream()

        response = test_client.get(
            f"/files/{task_history_response.id}/download?path=backup.sql"
        )

        assert response.status_code == HTTP_200_OK
        assert response.headers["content-disposition"] == (
            'attachment; filename="backup.sql"'
        )
        assert response.content == b"partial-"

    def test_no_path_streams_without_headers(
        self, test_client, mock_tasks_client_dep, task_history_response
    ):
        """Assert download without path query param streams without Content-Disposition."""
        mock_tasks_client_dep.stream_chunks.return_value = _mock_file_stream(
            [b"raw-data"]
        )

        response = test_client.get(f"/files/{task_history_response.id}/download")

        assert response.status_code == HTTP_200_OK
        assert "content-disposition" not in response.headers

    @pytest.mark.parametrize("root_path", ["", "/sep"])
    @pytest.mark.usefixtures("test_client")
    def test_download_keeps_both_the_disposition_and_the_proxy_header(
        self, mock_tasks_client_dep, task_history_response, root_path
    ):
        """Assert seeding the header dict leaves Content-Disposition intact."""
        mock_tasks_client_dep.get.return_value = {
            "backup.sql": {"size": 2048, "is_dir": False}
        }
        mock_tasks_client_dep.stream_chunks.return_value = _mock_file_stream([b"chunk"])
        client = TestClient(sep_app, root_path=root_path, raise_server_exceptions=False)

        response = client.get(
            f"{root_path}/files/{task_history_response.id}/download?path=backup.sql"
        )

        assert response.status_code == HTTP_200_OK
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["content-disposition"] == (
            'attachment; filename="backup.sql"'
        )

    @pytest.mark.parametrize("root_path", ["", "/sep"])
    @pytest.mark.usefixtures("test_client")
    def test_download_without_a_path_still_carries_the_proxy_header(
        self, mock_tasks_client_dep, task_history_response, root_path
    ):
        """Assert the no-disposition contract survives the seeded header dict."""
        mock_tasks_client_dep.stream_chunks.return_value = _mock_file_stream([b"raw"])
        client = TestClient(sep_app, root_path=root_path, raise_server_exceptions=False)

        response = client.get(f"{root_path}/files/{task_history_response.id}/download")

        assert response.status_code == HTTP_200_OK
        assert response.headers["x-accel-buffering"] == "no"
        assert "content-disposition" not in response.headers


class TestDownloadThroughTheRealClientDependency:
    """Cover ``download_task_history_file`` without stubbing ``get_tasks_client``."""

    pytestmark = pytest.mark.asyncio

    async def test_streamed_request_carries_the_access_token(
        self, app_state_tasks_client, async_test_client, task_history_response
    ):
        """Authenticate the body stream as the viewing user, not anonymously."""
        url = f"{TASKS_ENDPOINT}/history/{task_history_response.id}/file/"
        with aioresponses() as upstream:
            upstream.get(url, status=HTTP_200_OK, body=b"payload")

            response = await async_test_client.get(
                f"/files/{task_history_response.id}/download"
            )

            recorded = next(iter(upstream.requests.values()))[0]

        assert response.status_code == HTTP_200_OK
        assert response.content == b"payload"
        assert recorded.kwargs["headers"]["Authorization"] == "Bearer test-token"

    async def test_file_list_survives_a_rebind_while_a_consumer_holds(
        self, app_state_tasks_client, async_test_client, task_history_response
    ):
        """Keep a retired client serving the consumers that already hold it."""
        url = f"{TASKS_ENDPOINT}/history/{task_history_response.id}/files/"
        with aioresponses() as upstream:
            upstream.get(url, status=HTTP_200_OK, payload={})

            async with app_state_tasks_client.hold():
                await app_state_tasks_client.close_when_idle()

                response = await async_test_client.get(
                    f"/files/{task_history_response.id}"
                )

        assert response.status_code == HTTP_200_OK
        assert app_state_tasks_client._session is None

    @pytest.mark.usefixtures("async_test_client")
    async def test_download_survives_a_rebind_mid_transfer(
        self, app_state_tasks_client, task_history_response
    ):
        """Deliver a full download whose client was retired while the body was in flight."""
        release = asyncio.Event()

        async def held_body(_url, **_kwargs):
            await release.wait()
            return CallbackResult(status=HTTP_200_OK, body=b"payload")

        url = f"{TASKS_ENDPOINT}/history/{task_history_response.id}/file/"
        with aioresponses() as upstream:
            upstream.get(url, callback=held_body)

            async with asgi_stream(
                sep_app, f"/files/{task_history_response.id}/download"
            ) as response:
                assert response.status_code == HTTP_200_OK

                await app_state_tasks_client.close_when_idle()
                assert app_state_tasks_client._session is not None

                release.set()
                body = await response.drain()

        assert response.status_code == HTTP_200_OK
        assert body == b"payload"
        assert app_state_tasks_client._session is None

    @pytest.mark.usefixtures("async_test_client")
    async def test_disconnect_mid_stream_releases_the_hold(
        self, app_state_tasks_client, task_history_response
    ):
        """Close a retired client when the consumer disconnects mid-download.

        Abandoning the response cancels the request task, which is what a client
        closing the connection does. FastAPI unwinds the dependency exit stack,
        so the hold releases and the deferred close still fires rather than
        leaving the session open for the life of the process.

        This is what pins the shield around the deferred close: replacing it with
        a bare await leaves the session open here, while the unit-level
        cancellation test passes either way.
        """
        never_released = asyncio.Event()

        async def held_body(_url, **_kwargs):
            await never_released.wait()
            return CallbackResult(status=HTTP_200_OK, body=b"payload")

        url = f"{TASKS_ENDPOINT}/history/{task_history_response.id}/file/"
        with aioresponses() as upstream:
            upstream.get(url, callback=held_body)

            async with asgi_stream(
                sep_app, f"/files/{task_history_response.id}/download"
            ) as response:
                assert response.status_code == HTTP_200_OK

                await app_state_tasks_client.close_when_idle()
                assert app_state_tasks_client._session is not None

        assert app_state_tasks_client._session is None
