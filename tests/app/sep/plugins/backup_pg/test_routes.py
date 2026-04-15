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

"""Define tests for the app.sep.plugins.backup_pg.routes module."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from app.inventory.models import ServiceTypeEnum
from app.tasks.models import TaskHistoryStatusEnum


@pytest.mark.usefixtures("_mock_get_backups_index_context_dep")
def test_backups_index(test_client):
    """Test GET /backup-pg/ route."""
    response = test_client.get("/backup-pg/")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert (
        "<title>PostgreSQL Backups — Services Enablement Platform</title>"
        in response.text
    )


def test_backups_create(
    test_client, mock_task_api_dep, backup_create, mock_build_backup_task_payload_dep
):
    """Test POST /backup-pg/ route."""
    response = test_client.post(
        "/backup-pg/", data=backup_create.model_dump(), follow_redirects=False
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/backup-pg/{backup_create.task_name}"
    )

    mock_task_api_dep.post.assert_called_once()
    called_args, called_kwargs = mock_task_api_dep.post.call_args
    assert called_args[0] == "/"
    assert called_kwargs["json"] == mock_build_backup_task_payload_dep.model_dump()


@pytest.mark.usefixtures("_mock_get_backups_task_dep", "mock_get_username_mapping")
def test_backups_detail(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_task
):
    """Test GET /backup-pg/{task_name} route."""
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            {},
            {"items": [], "total": 0, "offset": 0, "limit": 50},
            {"items": [], "total": 0, "offset": 0, "limit": 50},
            [],
            {"items": [], "total": 0, "offset": 0, "limit": 50},
        ]
    )
    mock_inventory_api_dep.get = AsyncMock(
        return_value={"items": [], "total": 0, "offset": 0, "limit": 50}
    )

    response = test_client.get(f"/backup-pg/{created_task.name}")

    assert response.status_code == status.HTTP_200_OK
    assert (
        f"<title>Backups - {created_task.name} — Services Enablement Platform</title>"
        in response.text
    )

    mock_task_api_dep.get.assert_any_call(f"/{created_task.name}/history/")
    mock_task_api_dep.get.assert_any_call(
        f"/{created_task.name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    mock_task_api_dep.get.assert_any_call(f"/stats/{created_task.name}")


@pytest.mark.usefixtures("_mock_get_backups_task_dep", "mock_get_username_mapping")
def test_backups_detail_handles_inventory_error(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_task
):
    """Test detail route continues when inventory service lookup fails."""
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            {},
            {"items": [], "total": 0, "offset": 0, "limit": 50},
            {"items": [], "total": 0, "offset": 0, "limit": 50},
            [],
            {"items": [], "total": 0, "offset": 0, "limit": 50},
        ]
    )
    mock_inventory_api_dep.get = AsyncMock(side_effect=HTTPException(status_code=404))

    response = test_client.get(f"/backup-pg/{created_task.name}")

    assert response.status_code == status.HTTP_200_OK
    mock_inventory_api_dep.get.assert_any_call(
        "/services/",
        params={"service_type": ServiceTypeEnum.POSTGRESQL, "limit": 0},
    )


@pytest.mark.usefixtures(
    "_mock_get_backups_task_dep", "_mock_check_for_conflicted_running_tasks"
)
def test_backups_execute(test_client, mock_task_api_dep, created_task):
    """Test POST /backup-pg/{task_name} route with no chain_task_names."""
    response = test_client.post(
        f"/backup-pg/{created_task.name}", follow_redirects=False
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/backup-pg/{created_task.name}"
    )

    mock_task_api_dep.post.assert_called_once()
    called_args, called_kwargs = mock_task_api_dep.post.call_args
    assert called_args[0] == f"/execute/{created_task.name}"
    assert called_kwargs["json"] == {
        "eta": None,
        "chain_task_names": None,
        "chain_on_failure": None,
    }


@pytest.mark.usefixtures(
    "_mock_get_backups_task_dep", "_mock_check_for_conflicted_running_tasks"
)
def test_backups_execute_with_chain_task_names(
    test_client, mock_task_api_dep, created_task
):
    """Test POST /backup-pg/{task_name} passes chain_task_names to the tasks API."""
    response = test_client.post(
        f"/backup-pg/{created_task.name}",
        data={"chain_task_names": ["task-a", "task-b"]},
        follow_redirects=False,
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER

    called_args, called_kwargs = mock_task_api_dep.post.call_args
    assert called_args[0] == f"/execute/{created_task.name}"
    assert called_kwargs["json"]["chain_task_names"] == ["task-a", "task-b"]
