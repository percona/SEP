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

"""Define tests for the app.sep.apps.mysql_backups.restore.deps module."""

import pytest
from fastapi import HTTPException, status

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.spec import RESERVED_FORM_KEY
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.restore.deps import (
    build_restore_payload,
    build_restore_task_payload,
    resolve_restore_entities,
)
from app.sep.apps.mysql_backups.restore.models import RestoreCreate
from app.sep.inventory import CreatedService
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.models import TaskWrite


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
        "app.sep.apps.mysql_backups.restore.deps.get_created_entity",
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
    assert task_payload.owner == "RESTORES"
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
        "app.sep.apps.mysql_backups.restore.deps.get_created_entity",
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
async def test_resolve_restore_entities_mydumper_splits_address_and_resolves_schema(
    mocker,
    mock_remote_api,
    created_service: CreatedService,
):
    """Resolve the MyDumper service address split and the schema name."""
    node = created_service.node.model_copy(update={"address": "10.0.0.5"})
    service = created_service.model_copy(update={"node": node, "port": 3307})
    schema = service.model_copy(update={"name": "shop"})
    mocker.patch(
        "app.sep.apps.mysql_backups.restore.deps.get_created_entity",
        side_effect=[service, schema],
    )

    form = RestoreCreate(
        hostname="restore-host",
        task_name="restore-task",
        service_id=str(service.id),
        schema_id="42",
        backup_type=BackupType.MYDUMPER,
        backup_source="/var/backups/latest",
        datadir="/var/lib/mysql",
    )
    resolved = await resolve_restore_entities(form, mock_remote_api)

    assert resolved.service_name == service.name
    assert resolved.dest_host == node.address
    assert resolved.dest_port == service.port
    assert resolved.database == schema.name


@pytest.mark.asyncio
async def test_build_restore_task_payload_mydumper_without_service_id_raises(
    mocker,
    mock_remote_api,
):
    """MYDUMPER preserves the eager-raise contract when service_id is unset."""
    get_created_entity = mocker.patch(
        "app.sep.apps.mysql_backups.restore.deps.get_created_entity",
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

    with pytest.raises(HTTPException) as exc_info:
        await build_restore_task_payload(form, mock_remote_api)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    # Tighten the eager-raise contract: assert the lookup ran with the exact
    # args the MYDUMPER branch promises (None service_id, MYSQL filter). A
    # future refactor that gates the lookup behind ``if form.service_id`` would
    # silently keep ``assert_awaited_once`` green; ``assert_awaited_once_with``
    # surfaces the regression.
    get_created_entity.assert_awaited_once_with(
        mock_remote_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        None,
        type=ServiceTypeEnum.MYSQL,
    )


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
        "app.sep.apps.mysql_backups.restore.deps.get_created_entity",
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
@pytest.mark.parametrize("service_id", ["/", "external-db", "db01:3306"])
async def test_build_restore_task_payload_annotates_free_typed_service_without_lookup(
    backup_type: BackupType,
    service_id: str,
    mocker,
    mock_remote_api,
):
    """A free-typed service name annotates the task without an inventory lookup.

    ``ServiceRef(allow_custom=True)`` lets the form submit a name instead of an
    inventory id. Interpolating one into the detail URL is never valid, and
    ``"/"`` used to collapse to the services *collection* endpoint (whose
    paginated list fails ``CreatedService`` validation and 500s), so a
    non-numeric value must skip the lookup and stand in as the service name.
    """
    get_created_entity = mocker.patch(
        "app.sep.apps.mysql_backups.restore.deps.get_created_entity",
    )

    form = RestoreCreate(
        hostname="restore-host",
        task_name="restore-task",
        service_id=service_id,
        backup_type=backup_type,
        backup_source="/var/backups/latest",
        datadir="/var/lib/mysql",
    )
    task_payload = await build_restore_task_payload(form, mock_remote_api)

    assert task_payload.data["meta"]["_service_name"] == service_id
    get_created_entity.assert_not_called()


@pytest.mark.asyncio
async def test_build_restore_task_payload_mydumper_rejects_free_typed_service(
    mocker,
    mock_remote_api,
):
    """MYDUMPER needs a resolvable service, so a free-typed name is a clean 422.

    MyDumper derives ``dest_host`` / ``dest_port`` from the service address, which
    a typed name cannot supply. Rejecting it up front keeps the eager-resolve
    contract while replacing the former bogus-URL 500.
    """
    get_created_entity = mocker.patch(
        "app.sep.apps.mysql_backups.restore.deps.get_created_entity",
    )

    form = RestoreCreate(
        hostname="restore-host",
        task_name="restore-task",
        service_id="/",
        backup_type=BackupType.MYDUMPER,
        backup_source="/var/backups/latest",
        datadir="/var/lib/mysql",
    )

    with pytest.raises(HTTPException) as exc_info:
        await build_restore_task_payload(form, mock_remote_api)

    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    get_created_entity.assert_not_called()


@pytest.mark.asyncio
async def test_build_restore_payload_stamps_form_without_new_secret_exposure(
    mock_remote_api,
):
    """Assert the stamped ``_form`` re-carries a secret already held in ``data``.

    AC #3 invariant: ``_form`` introduces no plaintext secret ``data`` does not
    already persist, so ``master_password`` appears in both and stays equal.
    """
    form = RestoreCreate(
        hostname="restore-host",
        task_name="restore-task",
        service_id=None,
        backup_type=BackupType.XTRABACKUP,
        backup_source="/var/backups/latest",
        datadir="/var/lib/mysql",
        master_password="s3cret-pw",
    )

    task_payload = await build_restore_payload(form, mock_remote_api)

    assert task_payload.data[RESERVED_FORM_KEY]["master_password"] == "s3cret-pw"
    assert "s3cret-pw" in task_payload.data["meta"]["config"]


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
    """Resolve xtrabackup/binlog to node-only annotations on a stale service_id.

    ``RemoteAPI.get`` raises the project's ``HTTPNotFoundException`` on 404, which
    the narrowed handler swallows to fall back to a node-only annotation.
    """
    mocker.patch(
        "app.sep.apps.mysql_backups.restore.deps.get_created_entity",
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
