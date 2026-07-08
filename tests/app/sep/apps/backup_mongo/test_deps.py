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

"""Define tests for the app.sep.apps.backup_mongo.deps module."""

import pytest

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_mongo.deps import build_backup_task_payload
from app.sep.apps.backup_mongo.models import BackupCreate
from app.sep.inventory import CreatedService
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.models import TaskOwner, TaskWrite


@pytest.mark.asyncio
async def test_build_backup_task_payload_includes_service_name(
    mocker,
    mock_remote_api,
    backup_create: BackupCreate,
    mongo_service: CreatedService,
):
    """build_backup_task_payload fetches a MONGODB service and tags meta with its name."""
    get_created_entity = mocker.patch(
        "app.sep.apps.backup_mongo.deps.get_created_entity",
        return_value=mongo_service,
    )

    task_payload = await build_backup_task_payload(backup_create, mock_remote_api)

    assert isinstance(task_payload, TaskWrite)
    assert task_payload.owner == TaskOwner.BACKUP_MONGO
    assert task_payload.data["meta"]["_service_name"] == mongo_service.name

    get_created_entity.assert_awaited_once_with(
        mock_remote_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        backup_create.service_id,
        type=ServiceTypeEnum.MONGODB,
    )


@pytest.mark.asyncio
async def test_build_backup_task_payload_swallows_404_for_missing_service(
    mocker,
    mock_remote_api,
    backup_create: BackupCreate,
):
    """Resolve a stale service_id (deleted service) to a node-only annotation.

    ``RemoteAPI.get`` raises the project's ``HTTPNotFoundException`` on 404, which
    the narrowed handler swallows to fall back to a node-only annotation.
    """
    mocker.patch(
        "app.sep.apps.backup_mongo.deps.get_created_entity",
        side_effect=HTTPNotFoundException(),
    )

    task_payload = await build_backup_task_payload(backup_create, mock_remote_api)

    assert isinstance(task_payload, TaskWrite)
    assert "_service_name" not in task_payload.data["meta"]
