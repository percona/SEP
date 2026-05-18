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

"""Tests for the gascan plugin JSON API routes under /api/plugins/gascan/."""

import shlex
from datetime import datetime, UTC
from unittest.mock import AsyncMock, call

from fastapi import status

from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner


def build_gascan_task(name: str = "gascan-task") -> dict:
    """Build a fake gascan task payload for route tests."""
    return {
        "id": 1,
        "name": name,
        "backend": TaskBackendEnum.PROXY,
        "owner": TaskOwner.GASCAN,
        "is_template": False,
        "protected": False,
        "alert_on_fail": False,
        "data": {
            "task": "run-command",
            "meta": {
                "command": "gascan",
                "args": "-playbook=site.yml -limit=web",
                "target": "host1",
            },
        },
        "created_at": datetime.now(UTC),
        "updated_at": None,
        "created_by": "user@example.com",
        "last_updated_by": "user@example.com",
    }


def build_gascan_write_body(task_name: str = "gascan-task", **kwargs) -> dict:
    """Build a valid GascanTaskWrite-compatible request body."""
    return {
        "task_name": task_name,
        "hostname": "host1",
        "playbook": "site.yml",
        **kwargs,
    }


class TestGascanSchemaEndpoint:
    """Tests for GET /api/plugins/gascan/schema."""

    def test_gascan_schema_returns_plugin_metadata(self, test_client):
        """Assert schema endpoint exposes gascan plugin name and fields."""
        response = test_client.get("/api/plugins/gascan/schema")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "gascan"
        assert data["display_name"] == "Gascan Management"
        field_names = {
            field["name"] for section in data["forms"] for field in section["fields"]
        }
        assert {"task_name", "hostname", "playbook", "limit", "override"} <= field_names


class TestGascanListEndpoint:
    """Tests for GET /api/plugins/gascan/."""

    def test_gascan_list_returns_data(self, test_client, mock_task_api_dep):
        """Assert list endpoint returns gascan tasks filtered by owner."""
        task = build_gascan_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {"items": [task]},
                {"items": []},
            ]
        )

        response = test_client.get("/api/plugins/gascan/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "gascan-task"
        mock_task_api_dep.get.assert_any_call(
            "/",
            params={"owner": TaskOwner.GASCAN.value},
        )


class TestGascanCreateEndpoint:
    """Tests for POST /api/plugins/gascan/."""

    def test_gascan_create_posts_assembled_payload(
        self, test_client, mock_task_api_dep
    ):
        """Assert create endpoint builds gascan command args correctly."""
        created = build_gascan_task("new-gascan")
        mock_task_api_dep.post = AsyncMock(return_value=created)

        body = build_gascan_write_body(
            task_name="new-gascan",
            limit="db",
            override="x=1",
        )
        response = test_client.post("/api/plugins/gascan/", json=body)
        assert response.status_code == status.HTTP_201_CREATED

        posted = mock_task_api_dep.post.await_args.kwargs["json"]
        assert posted["owner"] == TaskOwner.GASCAN.value
        args = shlex.split(posted["data"]["meta"]["args"])
        assert "-playbook=site.yml" in args
        assert "-limit=db" in args
        assert "-override=x=1" in args


class TestGascanDetailAndDeleteEndpoints:
    """Tests for GET and DELETE /api/plugins/gascan/{task_name}."""

    def test_gascan_detail_returns_task(self, test_client, mock_task_api_dep):
        """Assert detail endpoint returns a single gascan task."""
        task = build_gascan_task("detail-task")
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                task,
                {"items": [{"status": TaskHistoryStatusEnum.SUCCESS}]},
            ]
        )

        response = test_client.get("/api/plugins/gascan/detail-task")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "detail-task"
        assert mock_task_api_dep.get.await_args_list[0] == call("/detail-task")

    def test_gascan_delete_removes_task(self, test_client, mock_task_api_dep):
        """Assert delete endpoint removes the task via Tasks API."""
        task = build_gascan_task("delete-me")
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.delete = AsyncMock()

        response = test_client.delete("/api/plugins/gascan/delete-me")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_task_api_dep.delete.assert_awaited_once_with("/delete-me")
