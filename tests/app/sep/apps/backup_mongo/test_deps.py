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

from app.core.exceptions import HTTPConflictException, HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_mongo.deps import (
    build_backup_task_payload,
    ensure_backup_group_update_preserves_names,
)
from app.sep.apps.backup_mongo.models import BackupCreate, BackupTaskWrite
from app.sep.inventory import CreatedService
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.models import TaskWrite


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
    assert task_payload.owner == "BACKUP_MONGO"
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


class TestBackupGroupRenameGuard:
    """Tests for ensure_backup_group_update_preserves_names."""

    def test_allows_matching_name(self) -> None:
        """Accept a submitted task_name equal to the parent name."""
        ensure_backup_group_update_preserves_names("parent-backup", "parent-backup")

    def test_rejects_rename(self) -> None:
        """Raise 409 when the submitted task_name differs from the parent name."""
        with pytest.raises(HTTPConflictException):
            ensure_backup_group_update_preserves_names("parent-backup", "renamed")


class TestBackupFormRoundTrip:
    """Guard the create-stamp -> edit-PUT body round-trip."""

    def test_stamped_create_form_revalidates_as_put_body(
        self, backup_create: BackupCreate
    ) -> None:
        """Re-validate the JSON-mode create form as the PUT body model.

        The generic edit page resubmits the stored ``_form`` (a
        :class:`BackupCreate` dump, carrying ``backup_type``) as the PUT body;
        :class:`BackupTaskWrite` must accept it, dropping the extra
        ``backup_type`` rather than rejecting it.
        """
        stamped = backup_create.model_dump(mode="json")

        body = BackupTaskWrite.model_validate(stamped)

        assert body.task_name == backup_create.task_name
        assert body.service_id == backup_create.service_id
        assert not hasattr(body, "backup_type")
