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

"""Tests for the SEP merged task-history JSON API at ``/api/sep/task-history/``."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.db.crud import DEFAULT_PAGINATION_LIMIT, DEFAULT_PAGINATION_OFFSET
from app.sep.main import sep_app
from app.tasks.models import TaskBackendEnum, TaskOwner
from tests.app.factories import TaskFactory

TWO_MERGED_HISTORY_ROWS = 2
TWO_UNIQUE_TASK_NAMES = 2
PROPAGATED_TEST_OFFSET = 5
PROPAGATED_TEST_LIMIT = 10


def _history_item(*, item_id: int, started_at: str, task_name: str) -> dict[str, Any]:
    task = TaskFactory.build(
        id=item_id,
        name=task_name,
        owner=TaskOwner.BACKUP_MONGO,
        backend=TaskBackendEnum.PROXY,
    )
    task_payload = task.model_dump(mode="json")
    task_payload["data"] = {
        "task": "run-python",
        "meta": {"target": "host1"},
        "payload": "file:///plugins/backup_mongo/pbm_config_payload",
    }
    return {
        "id": item_id,
        "status": "success",
        "started_at": started_at,
        "execution_request": {"task": task_name, "target": "host1"},
        "task": {**task_payload, "deleted_at": None},
    }


def _history_page(
    *, item_id: int, started_at: str, task_name: str, total: int = 1
) -> dict:
    return {
        "items": [
            _history_item(item_id=item_id, started_at=started_at, task_name=task_name)
        ],
        "total": total,
        "offset": 0,
        "limit": 50,
    }


class TestSepTaskHistoryEndpoint:
    """Tests for ``GET /api/sep/task-history/`` proxy and merge behavior."""

    def test_merges_history_for_multiple_task_names(
        self,
        test_client: TestClient,
        mock_task_api_dep,
    ) -> None:
        """Fetch each task upstream and return rows sorted newest-first."""
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                _history_page(
                    item_id=1,
                    started_at="2026-01-01T10:00:00+00:00",
                    task_name="parent",
                ),
                _history_page(
                    item_id=2,
                    started_at="2026-01-02T10:00:00+00:00",
                    task_name="parent-logical",
                ),
            ]
        )
        response = test_client.get(
            "/api/sep/task-history/",
            params=[("task_names", "parent"), ("task_names", "parent-logical")],
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [item["id"] for item in body["items"]] == [2, 1]
        assert body["total"] == TWO_MERGED_HISTORY_ROWS
        assert body["offset"] == DEFAULT_PAGINATION_OFFSET
        assert body["limit"] == DEFAULT_PAGINATION_LIMIT

    def test_forwards_status_offset_and_limit_to_upstream(
        self,
        test_client: TestClient,
        mock_task_api_dep,
    ) -> None:
        """Repeat the same query params on every upstream history call."""
        mock_task_api_dep.get = AsyncMock(
            return_value={
                "items": [],
                "total": 0,
                "offset": PROPAGATED_TEST_OFFSET,
                "limit": PROPAGATED_TEST_LIMIT,
            }
        )
        response = test_client.get(
            "/api/sep/task-history/",
            params=[
                ("task_names", "task-a"),
                ("task_names", "task-b"),
                ("status", "running"),
                ("offset", str(PROPAGATED_TEST_OFFSET)),
                ("limit", str(PROPAGATED_TEST_LIMIT)),
            ],
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["offset"] == PROPAGATED_TEST_OFFSET
        assert body["limit"] == PROPAGATED_TEST_LIMIT
        assert mock_task_api_dep.get.await_count == TWO_UNIQUE_TASK_NAMES
        mock_task_api_dep.get.assert_any_await(
            "/task-a/history/",
            params={
                "offset": PROPAGATED_TEST_OFFSET,
                "limit": PROPAGATED_TEST_LIMIT,
                "status": "running",
            },
        )
        mock_task_api_dep.get.assert_any_await(
            "/task-b/history/",
            params={
                "offset": PROPAGATED_TEST_OFFSET,
                "limit": PROPAGATED_TEST_LIMIT,
                "status": "running",
            },
        )

    def test_deduplicates_repeated_task_names(
        self,
        test_client: TestClient,
        mock_task_api_dep,
    ) -> None:
        """Query each unique task name only once."""
        mock_task_api_dep.get = AsyncMock(
            return_value={"items": [], "total": 0, "offset": 0, "limit": 50}
        )
        response = test_client.get(
            "/api/sep/task-history/",
            params=[
                ("task_names", "task-a"),
                ("task_names", "task-a"),
                ("task_names", "task-b"),
            ],
        )
        assert response.status_code == status.HTTP_200_OK
        assert mock_task_api_dep.get.await_count == TWO_UNIQUE_TASK_NAMES

    def test_rejects_empty_task_names(
        self,
        test_client: TestClient,
        mock_task_api_dep,
    ) -> None:
        """Return 422 when every supplied task name is blank."""
        response = test_client.get(
            "/api/sep/task-history/",
            params=[("task_names", ""), ("task_names", "   ")],
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_task_api_dep.get.assert_not_called()


class TestSepTaskHistoryAuth:
    """Tests for ``/api/sep/task-history/`` authentication enforcement."""

    @pytest.fixture
    def unauthenticated_client(self) -> TestClient:
        """Yield a TestClient with no auth dependency overrides applied."""
        previous = sep_app.dependency_overrides
        sep_app.dependency_overrides = {}
        try:
            yield TestClient(sep_app, raise_server_exceptions=False)
        finally:
            sep_app.dependency_overrides = previous

    def test_unauthenticated_returns_json_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Reject anonymous requests with a JSON 401 response."""
        response = unauthenticated_client.get(
            "/api/sep/task-history/",
            params=[("task_names", "foo")],
            follow_redirects=False,
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()
