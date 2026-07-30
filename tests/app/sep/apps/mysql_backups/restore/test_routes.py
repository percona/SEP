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

"""Define tests for the app.sep.apps.mysql_backups.restore.routes module."""

from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import status

from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.restore.deps import (
    get_restores_index_context,
    get_restores_task,
)
from app.sep.apps.mysql_backups.restore.models import RestoreCreate
from app.sep.inventory import CreatedService
from app.sep.main import sep_app
from app.tasks.models import TaskHistoryStatusEnum
from tests.app.factories import TaskFactory


@pytest.fixture
def _mock_get_restores_index_context_dep():
    """Mock the get_restores_index_context dependency with default user context."""
    sep_app.dependency_overrides[get_restores_index_context] = lambda: {
        "user": "default_user"
    }
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def created_restore_task():
    """Return a fake Task instance owned by Restores."""
    return TaskFactory.build(
        owner="RESTORES",
        data={
            "meta": {
                "target": "restore-host",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "BACKUP_TYPE": BackupType.MYDUMPER.value,
                                "DEST_HOST": "dest-host",
                                "DEST_PORT": 3306,
                            }
                        ]
                    }
                ),
            }
        },
    )


@pytest.fixture
def _mock_get_restores_task_dep(created_restore_task):
    """Mock the get_restores_task dependency."""
    sep_app.dependency_overrides[get_restores_task] = lambda: created_restore_task
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_get_restores_index_context_dep")
def test_restores_index(test_client):
    """Test GET /mysql_backups/restores/ route."""
    response = test_client.get("/mysql_backups/restores/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "<title>Restores — Services Enablement Platform</title>" in response.text


@pytest.mark.usefixtures("_mock_get_restores_task_dep", "mock_get_username_mapping")
def test_restores_detail(
    test_client, mock_task_api_dep, mock_inventory_api_dep, created_restore_task
):
    """Test GET /mysql_backups/restores/{task_name} route."""
    mock_task_api_dep.get = AsyncMock(
        side_effect=[
            {},  # /hosts/
            {"items": [], "total": 0, "offset": 0, "limit": 50},  # history
            {"items": [], "total": 0, "offset": 0, "limit": 50},  # running_tasks
            [],  # stats
            {"items": [], "total": 0, "offset": 0, "limit": 50},  # chainable_tasks
        ]
    )
    mock_inventory_api_dep.get.return_value = {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 50,
    }
    response = test_client.get(f"/mysql_backups/restores/{created_restore_task.name}")
    assert response.status_code == status.HTTP_200_OK
    assert (
        f"<title>Restores - {created_restore_task.name} — Services Enablement Platform</title>"
        in response.text
    )
    assert (
        f"/mysql_backups/restores/{created_restore_task.name}/delete" in response.text
    )
    assert f"/tasks/{created_restore_task.name}/delete" not in response.text
    mock_task_api_dep.get.assert_any_call(f"/{created_restore_task.name}/history/")
    mock_task_api_dep.get.assert_any_call(
        f"/{created_restore_task.name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    mock_task_api_dep.get.assert_any_call(f"/stats/{created_restore_task.name}")


@pytest.fixture
def restore_create_factory(created_service: CreatedService):
    """Build a ``RestoreCreate`` form for the requested backup_type."""

    def _build(backup_type: BackupType) -> RestoreCreate:
        return RestoreCreate(
            hostname="restore-host",
            task_name="restore-task",
            service_id=str(created_service.id),
            backup_type=backup_type,
            backup_source="/var/backups/latest",
            datadir="/var/lib/mysql",
        )

    return _build


@pytest.mark.parametrize(
    "backup_type",
    [BackupType.MYDUMPER, BackupType.XTRABACKUP, BackupType.BINLOG],
)
def test_restores_create_full_form_dependency_chain_without_payload_override(
    backup_type: BackupType,
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    created_service,
    restore_create_factory,
):
    """POST /mysql_backups/restores/ resolves the real dep graph and tags meta with _service_name."""
    form = restore_create_factory(backup_type)
    mock_inventory_api_dep.get = AsyncMock(return_value=created_service.model_dump())
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post(
        "/mysql_backups/restores/",
        data=form.model_dump(exclude_none=True),
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_awaited_once()
    posted = mock_task_api_dep.post.await_args.kwargs["json"]
    assert posted["name"] == form.task_name
    assert posted["data"]["meta"]["_service_name"] == created_service.name


def test_restores_update_full_form_dependency_chain_without_payload_override(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    created_service,
    restore_create_factory,
):
    """POST /mysql_backups/restores/{task_name}/update resolves the real dep graph for updates too."""
    form = restore_create_factory(BackupType.XTRABACKUP)
    mock_inventory_api_dep.get = AsyncMock(return_value=created_service.model_dump())
    mock_task_api_dep.put.return_value = AsyncMock()

    response = test_client.post(
        f"/mysql_backups/restores/{form.task_name}/update",
        data=form.model_dump(exclude_none=True),
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.put.assert_awaited_once()
    posted = mock_task_api_dep.put.await_args.kwargs["json"]
    assert posted["data"]["meta"]["_service_name"] == created_service.name
