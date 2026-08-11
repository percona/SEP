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

from app.sep.apps.framework.spec import RESERVED_FORM_KEY
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.restore.deps import (
    build_restore_payload,
    resolve_restore_entities,
)
from app.sep.apps.mysql_backups.restore.models import RestoreCreate
from app.sep.inventory import CreatedService


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
