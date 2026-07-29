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

"""Tests for the tasks plugin JSON API routes under /api/apps/tasks/."""

from datetime import datetime, UTC
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status

from app.core.exceptions import HTTPNotFoundException
from app.sep.deps import get_task_by_name
from app.sep.main import sep_app
from app.tasks.models import (
    SYSTEM_USER,
    Task,
    TaskBackendEnum,
    TaskHistoryStatusEnum,
)
from tests.app.factories import TaskFactory

API_BASE = "/api/apps/tasks"
EXPECTED_TEMPLATE_DETAIL_CALLS = 2
DEFAULT_PAGE_LIMIT = 50
TOTAL_BEYOND_PAGE = 60
FORWARDED_OFFSET = 50
FORWARDED_LIMIT = 10


def build_task_payload(**overrides: Any) -> dict:
    """Build a fake tasks plugin task payload for route tests.

    :param overrides: Field overrides passed to ``TaskFactory.build``.
    :type overrides: Any
    :return: A task payload shaped like the Tasks API response.
    :rtype: dict
    """
    task = TaskFactory.build(**overrides)
    return task.model_dump(mode="json")


class TestTasksAppSchemaEndpoint:
    """Tests for GET /api/apps/tasks/schema."""

    def test_schema_returns_200(self, test_client):
        """Ensure the schema endpoint returns HTTP 200 with JSON content."""
        response = test_client.get(f"{API_BASE}/schema")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]

    def test_schema_plugin_name(self, test_client):
        """Ensure the schema body carries the tasks plugin name."""
        response = test_client.get(f"{API_BASE}/schema")

        assert response.json()["name"] == "tasks"

    def test_schema_has_no_forms(self, test_client):
        """Ensure the read-only plugin schema declares no forms."""
        response = test_client.get(f"{API_BASE}/schema")

        assert response.json()["forms"] == []

    def test_schema_list_view_columns(self, test_client):
        """Ensure the list view exposes the expected monitoring columns."""
        response = test_client.get(f"{API_BASE}/schema")

        column_keys = {
            column["key"] for column in response.json()["list_view"]["columns"]
        }
        assert column_keys == {
            "name",
            "backend",
            "created_at",
            "created_by",
            "last_updated_by",
        }


class TestTasksPluginListEndpoint:
    """Tests for GET /api/apps/tasks/."""

    @pytest.fixture(autouse=True)
    def _mock_username_mapping(self):
        """Avoid live Casdoor calls when list routes resolve user display names."""
        with patch(
            "app.sep.apps.tasks.api_routes.get_username_mapping",
            new_callable=AsyncMock,
            return_value={},
        ):
            yield

    def test_list_returns_empty_envelope(self, test_client, mock_task_api_dep):
        """Ensure an empty upstream list maps to an empty paginated envelope."""
        mock_task_api_dep.get = AsyncMock(
            return_value={"items": [], "total": 0, "offset": 0, "limit": 50}
        )

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["offset"] == 0
        assert body["limit"] == DEFAULT_PAGE_LIMIT
        mock_task_api_dep.get.assert_awaited_once_with(
            "/", params={"offset": 0, "limit": DEFAULT_PAGE_LIMIT}
        )

    def test_list_maps_task_rows(self, test_client, mock_task_api_dep):
        """Ensure upstream task items are projected into list response rows."""
        created_at = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
        task = build_task_payload(
            name="monitor-task",
            created_at=created_at,
            created_by="creator-id",
            last_updated_by="editor-id",
        )
        mock_task_api_dep.get = AsyncMock(
            return_value={"items": [task], "total": 1, "offset": 0, "limit": 50}
        )

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        row = body["items"][0]
        assert row["name"] == "monitor-task"
        assert row["backend"] == TaskBackendEnum.NOMAD
        assert row["created_at"] == task["created_at"]
        assert row["created_by"] == "creator-id"
        assert row["last_updated_by"] == "editor-id"

    def test_list_exposes_total_beyond_page(self, test_client, mock_task_api_dep):
        """Ensure a >50-task list exposes the upstream total and is not truncated."""
        page = [
            build_task_payload(name=f"task-{index}")
            for index in range(DEFAULT_PAGE_LIMIT)
        ]
        mock_task_api_dep.get = AsyncMock(
            return_value={
                "items": page,
                "total": TOTAL_BEYOND_PAGE,
                "offset": 0,
                "limit": DEFAULT_PAGE_LIMIT,
            }
        )

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == TOTAL_BEYOND_PAGE
        assert len(body["items"]) == DEFAULT_PAGE_LIMIT

    def test_list_forwards_offset_and_limit(self, test_client, mock_task_api_dep):
        """Ensure offset/limit query params are forwarded upstream and echoed."""
        mock_task_api_dep.get = AsyncMock(
            return_value={
                "items": [],
                "total": TOTAL_BEYOND_PAGE,
                "offset": FORWARDED_OFFSET,
                "limit": FORWARDED_LIMIT,
            }
        )

        response = test_client.get(
            f"{API_BASE}/?offset={FORWARDED_OFFSET}&limit={FORWARDED_LIMIT}"
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["offset"] == FORWARDED_OFFSET
        assert body["limit"] == FORWARDED_LIMIT
        mock_task_api_dep.get.assert_awaited_once_with(
            "/", params={"offset": FORWARDED_OFFSET, "limit": FORWARDED_LIMIT}
        )

    @patch(
        "app.sep.apps.tasks.api_routes.get_username_mapping",
        new_callable=AsyncMock,
    )
    def test_list_resolves_user_ids_to_usernames(
        self,
        mock_username_mapping,
        test_client,
        mock_task_api_dep,
        admin_user,
    ):
        """Ensure list rows show Casdoor usernames like the legacy tasks list page."""
        admin_user_id = str(admin_user.id)
        mock_username_mapping.return_value = {admin_user_id: "Admin"}
        task = build_task_payload(
            name="monitor-task",
            created_by=SYSTEM_USER,
            last_updated_by=admin_user_id,
        )
        mock_task_api_dep.get = AsyncMock(
            return_value={"items": [task], "total": 1, "offset": 0, "limit": 50}
        )

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        row = response.json()["items"][0]
        assert row["created_by"] == SYSTEM_USER
        assert row["last_updated_by"] == "Admin"


class TestTasksPluginDetailEndpoint:
    """Tests for GET /api/apps/tasks/{task_name}."""

    def test_detail_returns_bundle(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure the detail endpoint aggregates task, history, periodic, running, and hosts."""
        task = build_task_payload(name="detail-task")
        periodic = [
            {
                "id": 1,
                "name": "nightly",
                "enabled": True,
                "period": "0 0 * * *",
                "next_run_at": "2026-05-20T00:00:00+00:00",
                "last_run_at": None,
                "total_run_count": 3,
                "last_run_status": TaskHistoryStatusEnum.SUCCESS.value,
                "execute_request": {"chain_task_names": ["follow-up-task"]},
            }
        ]
        history = {
            "items": [
                {"id": 10, "status": TaskHistoryStatusEnum.SUCCESS.value},
                {"id": 11, "status": TaskHistoryStatusEnum.RUNNING.value},
            ],
            "total": 2,
            "offset": 0,
            "limit": 50,
        }
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                task,
                {"nomad-1": "10.0.0.1"},
                periodic,
                history,
            ]
        )
        mock_inventory_api_dep.get = AsyncMock(
            return_value={"items": [{"name": "inv-node", "address": "10.0.0.1"}]}
        )

        response = test_client.get(f"{API_BASE}/detail-task")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["task"]["name"] == "detail-task"
        assert body["execution_history"] == history
        assert body["periodic_summary"] == [
            {
                "id": 1,
                "name": "nightly",
                "enabled": True,
                "period": "0 0 * * *",
                "next_run_at": "2026-05-20T00:00:00Z",
                "last_run_at": None,
                "total_run_count": 3,
                "last_run_status": "success",
                "chain_task_names": ["follow-up-task"],
            }
        ]
        assert body["executor_hosts"] == [
            {"value": "nomad-1", "label": "inv-node"},
        ]
        mock_task_api_dep.get.assert_any_await("/detail-task/periodic/")
        mock_task_api_dep.get.assert_any_await("/detail-task/history/")

    def test_detail_skips_periodic_and_history_for_templates(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure template tasks return only the definition and executor host metadata."""
        task = build_task_payload(name="template-task", is_template=True)
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                task,
                {"nomad-1": "10.0.0.1"},
            ]
        )
        mock_inventory_api_dep.get = AsyncMock(return_value={"items": []})

        response = test_client.get(f"{API_BASE}/template-task")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["task"]["name"] == "template-task"
        assert body["execution_history"] == {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 0,
        }
        assert body["periodic_summary"] == []
        assert body["executor_hosts"] == [{"value": "nomad-1", "label": "nomad-1"}]
        assert mock_task_api_dep.get.await_count == EXPECTED_TEMPLATE_DETAIL_CALLS

    def test_detail_returns_404_when_task_lookup_raises(
        self, test_client, mock_task_api_dep
    ):
        """Ensure a missing task returns 404 before any history or periodic calls."""

        async def task_not_found() -> Task:
            raise HTTPNotFoundException

        sep_app.dependency_overrides[get_task_by_name] = task_not_found
        response = test_client.get(f"{API_BASE}/missing-task")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"detail": "Not Found"}
        mock_task_api_dep.get.assert_not_called()

    def test_detail_returns_404_for_invalid_upstream_payload(
        self, test_client, mock_task_api_dep
    ):
        """Ensure invalid task payloads from the tasks API surface as 404."""
        mock_task_api_dep.get = AsyncMock(return_value={"not": "a-task"})

        response = test_client.get(f"{API_BASE}/bad-task")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_task_api_dep.get.assert_awaited_once_with("/bad-task")
