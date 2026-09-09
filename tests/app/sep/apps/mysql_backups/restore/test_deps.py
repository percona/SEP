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
    _declared_source_override,
    build_restore_api_task_response,
    build_restore_payload,
    resolve_restore_entities,
)
from app.sep.apps.mysql_backups.restore.models import RestoreCreate, SourceTransport
from app.sep.inventory import CreatedService
from app.tasks.models import Task, TaskBackendEnum


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
        # The replication options are gated on their parent toggle, so a
        # password only reaches the payload with replication actually on.
        slave_from_master=True,
        master_password="s3cret-pw",
    )

    task_payload = await build_restore_payload(form, mock_remote_api)

    assert task_payload.data[RESERVED_FORM_KEY]["master_password"] == "s3cret-pw"
    assert "s3cret-pw" in task_payload.data["meta"]["config"]


_NON_DEFAULT_SSH_PORT = 2222


def _restore_task(stored_form: dict | None) -> Task:
    """Build a restore task row, optionally carrying a stored form stamp."""
    data = {
        "task": "run-python",
        "meta": {"target": "executor-1", "config": ""},
    }
    if stored_form is not None:
        data[RESERVED_FORM_KEY] = stored_form
    return Task(
        name="restore-task",
        owner="RESTORES",
        backend=TaskBackendEnum.PROXY,
        data=data,
        protected=False,
        alert_on_fail=False,
    )


def test_served_stamp_declares_the_source_its_stored_values_imply():
    """Serve a pre-declaration stamp with the transport its own values imply.

    The edit form seeds a field the stamp does not carry from the schema default,
    so serving such a stamp untouched would open the form on ``local`` and hide
    the SSH credentials. A hidden field is dropped from the submission, so the
    next save would discard them.
    """
    task = _restore_task(
        {
            "task_name": "restore-task",
            "hostname": "executor-1",
            "backup_type": BackupType.XTRABACKUP.value,
            "backup_source": "db01:/backups/xb/latest",
            "ssh_user": "deploy",
            "ssh_port": _NON_DEFAULT_SSH_PORT,
            "ssh_key": "prod-key",
            "s3_tool": "s3cmd",
        }
    )

    served = build_restore_api_task_response(task).data[RESERVED_FORM_KEY]

    assert served["source_transport"] == SourceTransport.SSH.value
    assert served["ssh_user"] == "deploy"
    assert served["ssh_port"] == _NON_DEFAULT_SSH_PORT
    assert served["ssh_key"] == "prod-key"


def test_served_stamp_keeps_a_declaration_the_operator_already_made():
    """Leave a stamp that already declares its source untouched."""
    stored_form = {
        "task_name": "restore-task",
        "hostname": "executor-1",
        "backup_type": BackupType.MYDUMPER.value,
        "backup_source": "/backups/mydumper/latest",
        "source_transport": SourceTransport.LOCAL.value,
    }

    served = build_restore_api_task_response(_restore_task(stored_form)).data

    assert served[RESERVED_FORM_KEY] == stored_form


def test_an_unvalidatable_stamp_is_served_rather_than_failing_the_route():
    """Serve a stamp that cannot validate unchanged, so one bad task cannot break the list."""
    stored_form = {"task_name": "restore-task", "backup_source": "$(id)"}

    served = build_restore_api_task_response(_restore_task(stored_form)).data

    assert served[RESERVED_FORM_KEY] == stored_form


def test_a_task_without_a_stamp_is_served_unchanged():
    """Leave a legacy task carrying no stamp alone."""
    served = build_restore_api_task_response(_restore_task(None)).data

    assert RESERVED_FORM_KEY not in served


def test_stored_stamp_repair_tolerates_a_legacy_replication_combination():
    """Repair a pre-source-controls stamp that also predates the gating.

    ``_declared_source_override`` swallows a validation error, so validating the
    stored stamp with the strict model would silently skip the repair for the
    exact population it exists to serve — a stamp old enough to lack the source
    controls is also old enough to carry a replication option with
    ``slave_from_master`` off.
    """
    stored_form = {
        "task_name": "restore-legacy",
        "hostname": "executor-host",
        "backup_type": BackupType.XTRABACKUP.value,
        "backup_source": "/data/backups/latest",
        "slave_from_master": False,
        "master_ip": "10.0.0.9",
    }
    task = _restore_task(stored_form)

    override = _declared_source_override(task)

    declared = override["data"][RESERVED_FORM_KEY]
    assert declared["source_transport"] == SourceTransport.LOCAL.value
    assert declared["master_ip"] == "10.0.0.9"
