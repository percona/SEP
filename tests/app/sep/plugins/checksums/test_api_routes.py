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

"""Tests for the checksums plugin JSON API routes."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, call, patch

from fastapi import status

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner


def build_checksum_task(name: str = "checksum-task") -> dict:
    """Build a fake checksums task payload for route tests."""
    return {
        "id": 1,
        "name": name,
        "backend": TaskBackendEnum.PROXY,
        "owner": TaskOwner.CHECKSUMS,
        "is_template": False,
        "protected": False,
        "alert_on_fail": False,
        "data": {
            "task": "run-command",
            "meta": {
                "command": "pt-table-checksum",
                "args": "--recursion-method=processlist",
                "target": "host1",
                "_service_name": "test-service",
                "_service_host": "127.0.0.1",
                "_service_port": 3306,
            },
        },
        "created_at": datetime.now(UTC),
        "updated_at": None,
        "created_by": "user@example.com",
        "last_updated_by": "user@example.com",
    }


def test_checksums_api_list_returns_data(test_client, mock_task_api_dep):
    """Ensure the checksums API list returns task data."""
    task = build_checksum_task()
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            [task],
            [{"status": TaskHistoryStatusEnum.SUCCESS.value}],
        ]
    )

    response = test_client.get("/checksums/api/")

    assert response.status_code == status.HTTP_200_OK
    assert "application/json" in response.headers["content-type"]

    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == task["name"]
    assert data[0]["service_type"] == ServiceTypeEnum.MYSQL.value
    assert data[0]["status"] == TaskHistoryStatusEnum.SUCCESS.value


def test_checksums_api_list_returns_empty_array(test_client, mock_task_api_dep):
    """Ensure the checksums API returns an empty list when no tasks exist."""
    mock_task_api_dep.get.return_value = []

    response = test_client.get("/checksums/api/")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


def test_checksums_api_list_returns_empty_array_for_non_mysql_service_type(
    test_client, mock_task_api_dep
):
    """Ensure the checksums API returns an empty list for unsupported service types."""
    response = test_client.get(
        "/checksums/api/",
        params={"service_type": ServiceTypeEnum.POSTGRESQL.value},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []
    mock_task_api_dep.get.assert_not_called()


def test_checksums_api_list_filters_by_service_type_and_status(
    test_client, mock_task_api_dep
):
    """Ensure the checksums API filters tasks by service type and status."""
    task = build_checksum_task()
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            [task],
            [{"status": TaskHistoryStatusEnum.RUNNING.value}],
        ]
    )

    response = test_client.get(
        "/checksums/api/",
        params={
            "service_type": ServiceTypeEnum.MYSQL.value,
            "status": TaskHistoryStatusEnum.RUNNING.value,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == task["name"]
    assert data[0]["status"] == TaskHistoryStatusEnum.RUNNING.value

    assert mock_task_api_dep.get.call_args_list == [
        call("/", params={"owner": TaskOwner.CHECKSUMS.value}),
        call(f"/{task['name']}/history/"),
    ]


def test_checksums_api_detail_returns_task(test_client, mock_task_api_dep):
    """Ensure the checksums API detail endpoint returns a single task."""
    task = build_checksum_task()
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            task,
            [{"status": TaskHistoryStatusEnum.FAILED.value}],
        ]
    )

    response = test_client.get(f"/checksums/api/{task['name']}")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["name"] == task["name"]
    assert body["service_type"] == ServiceTypeEnum.MYSQL.value
    assert body["status"] == TaskHistoryStatusEnum.FAILED.value


def test_checksums_api_detail_returns_404(test_client, mock_task_api_dep):
    """Ensure the checksums API detail endpoint returns 404 for missing tasks."""
    non_existent_task_name = "nonexistent"
    with patch(
        "app.sep.plugins.checksums.routes.get_checksums_task",
        new=AsyncMock(side_effect=HTTPNotFoundException()),
    ) as mock_get_checksums_task:
        response = test_client.get(f"/checksums/api/{non_existent_task_name}")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "application/json" in response.headers["content-type"]
    assert response.json() == {"detail": "Not Found"}
    mock_get_checksums_task.assert_awaited_once_with(
        non_existent_task_name,
        mock_task_api_dep,
    )
