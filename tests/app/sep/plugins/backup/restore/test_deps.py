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

"""Define tests for the app.sep.plugins.backup.restore.deps module."""

import pytest

from app.core.exceptions import HTTPNotFoundException
from app.sep.inventory import CreatedService
from app.sep.plugins.backup.models import BackupType
from app.sep.plugins.backup.restore.deps import build_restore_task_payload
from app.sep.plugins.backup.restore.models import RestoreCreate
from app.tasks.models import TaskOwner, TaskWrite


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "backup_type",
    [BackupType.MYDUMPER, BackupType.XTRABACKUP, BackupType.BINLOG],
)
async def test_build_restore_task_payload_includes_service_name_when_service_id_set(
    backup_type: BackupType,
    mocker,
    mock_remote_api,
    created_service: CreatedService,
):
    """All MySQL restore branches inject ``_service_name`` when service_id is set."""
    mocker.patch(
        "app.sep.plugins.backup.restore.deps.get_created_entity",
        return_value=created_service,
    )

    form = RestoreCreate(
        hostname="restore-host",
        task_name="restore-task",
        service_id=str(created_service.id),
        backup_type=backup_type,
        backup_source="/var/backups/latest",
        datadir="/var/lib/mysql",
    )
    task_payload = await build_restore_task_payload(form, mock_remote_api)

    assert isinstance(task_payload, TaskWrite)
    assert task_payload.owner == TaskOwner.RESTORES
    assert task_payload.data["meta"]["_service_name"] == created_service.name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "backup_type",
    [BackupType.XTRABACKUP, BackupType.BINLOG],
)
async def test_build_restore_task_payload_omits_service_name_when_service_id_unset(
    backup_type: BackupType,
    mocker,
    mock_remote_api,
):
    """xtrabackup/binlog skip the service lookup and meta key when service_id is None."""
    get_created_entity = mocker.patch(
        "app.sep.plugins.backup.restore.deps.get_created_entity",
    )

    form = RestoreCreate(
        hostname="restore-host",
        task_name="restore-task",
        service_id=None,
        backup_type=backup_type,
        backup_source="/var/backups/latest",
        datadir="/var/lib/mysql",
    )
    task_payload = await build_restore_task_payload(form, mock_remote_api)

    assert "_service_name" not in task_payload.data["meta"]
    get_created_entity.assert_not_called()


@pytest.mark.asyncio
async def test_build_restore_task_payload_mydumper_without_service_id_raises(
    mocker,
    mock_remote_api,
):
    """MYDUMPER preserves the eager-raise contract when service_id is unset."""
    get_created_entity = mocker.patch(
        "app.sep.plugins.backup.restore.deps.get_created_entity",
        side_effect=HTTPNotFoundException(),
    )

    form = RestoreCreate(
        hostname="restore-host",
        task_name="restore-task",
        service_id=None,
        backup_type=BackupType.MYDUMPER,
        backup_source="/var/backups/latest",
        datadir="/var/lib/mysql",
    )

    with pytest.raises(HTTPNotFoundException):
        await build_restore_task_payload(form, mock_remote_api)

    get_created_entity.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "backup_type",
    [BackupType.XTRABACKUP, BackupType.BINLOG],
)
async def test_build_restore_task_payload_skips_lookup_for_unknown_service_sentinel(
    backup_type: BackupType,
    mocker,
    mock_remote_api,
):
    """xtrabackup/binlog with the ``-1`` UI sentinel skip the lookup entirely."""
    get_created_entity = mocker.patch(
        "app.sep.plugins.backup.restore.deps.get_created_entity",
    )

    form = RestoreCreate(
        hostname="restore-host",
        task_name="restore-task",
        service_id="-1",
        backup_type=backup_type,
        backup_source="/var/backups/latest",
        datadir="/var/lib/mysql",
    )
    task_payload = await build_restore_task_payload(form, mock_remote_api)

    assert "_service_name" not in task_payload.data["meta"]
    get_created_entity.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "backup_type",
    [BackupType.XTRABACKUP, BackupType.BINLOG],
)
async def test_build_restore_task_payload_swallows_404_for_non_mydumper(
    backup_type: BackupType,
    mocker,
    mock_remote_api,
):
    """xtrabackup/binlog gracefully degrade to node-only annotations on stale service_id."""
    mocker.patch(
        "app.sep.plugins.backup.restore.deps.get_created_entity",
        side_effect=HTTPNotFoundException(),
    )

    form = RestoreCreate(
        hostname="restore-host",
        task_name="restore-task",
        service_id="999999",
        backup_type=backup_type,
        backup_source="/var/backups/latest",
        datadir="/var/lib/mysql",
    )
    task_payload = await build_restore_task_payload(form, mock_remote_api)

    assert "_service_name" not in task_payload.data["meta"]
