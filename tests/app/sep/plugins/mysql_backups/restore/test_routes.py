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

"""Define tests for the app.sep.plugins.mysql_backups.restore.routes module."""

from unittest.mock import AsyncMock

import pytest
from fastapi import status

from app.sep.inventory import CreatedService
from app.sep.plugins.mysql_backups.models import BackupType
from app.sep.plugins.mysql_backups.restore.models import RestoreCreate


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
    """POST /backups/restores/ resolves the real dep graph and tags meta with _service_name."""
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
    """POST /backups/restores/{task_name}/update resolves the real dep graph for updates too."""
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
