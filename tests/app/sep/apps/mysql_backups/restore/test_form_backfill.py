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

"""Tests for the mysql restores legacy form reconstructor."""

from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.form_backfill import _backfill_single_task
from app.sep.apps.framework.form_backfill_inventory import (
    SchemaIdLookup,
    ServiceIdLookup,
)
from app.sep.apps.framework.form_backfill_registry import FormBackfillContext
from app.sep.apps.framework.spec import RESERVED_FORM_KEY
from app.sep.apps.mysql_backups.models import BackupType
from app.sep.apps.mysql_backups.restore.form_backfill import (
    FORM_BACKFILL_ENTRY,
    LegacyRestoreCreate,
    reconstruct_mysql_restores_form,
)
from app.sep.apps.mysql_backups.restore.models import (
    RestoreCreate,
    SourceTransport,
)
from app.sep.connectivity import CONNECTIVITY_META_HOST_KEY, CONNECTIVITY_META_PORT_KEY
from app.tasks.models import Task, TaskBackendEnum
from tests.app.sep.apps.mysql_backups.restore.conftest import legacy_default


def _service(
    service_id: int,
    *,
    name: str,
    address: str,
    port: int | None,
) -> SimpleNamespace:
    """Build a minimal inventory service record for lookup tests."""
    return SimpleNamespace(
        id=service_id,
        type=ServiceTypeEnum.MYSQL,
        name=name,
        port=port,
        node=SimpleNamespace(address=address),
    )


def _schema(schema_id: int, *, service_id: int, name: str) -> SimpleNamespace:
    """Build a minimal inventory schema record for lookup tests."""
    return SimpleNamespace(id=schema_id, service_id=service_id, name=name)


def _lookups(
    *services: SimpleNamespace,
    schemas: tuple[SimpleNamespace, ...] = (),
) -> tuple[ServiceIdLookup, SchemaIdLookup]:
    """Build service and schema lookup tables for restore tests."""
    return (
        ServiceIdLookup.from_services(services),
        SchemaIdLookup.from_schemas(schemas),
    )


def _ctx(
    service_lookup: ServiceIdLookup,
    schema_lookup: SchemaIdLookup | None = None,
) -> FormBackfillContext:
    """Return a backfill context wired to the supplied lookup tables."""
    return FormBackfillContext(
        log=__import__("logging").getLogger("test"),
        service_lookup=service_lookup,
        schema_lookup=schema_lookup,
    )


def _legacy_restore_task(
    *,
    name: str = "mysql-restore-legacy",
    target: str = "executor-1",
    backup_type: BackupType = BackupType.XTRABACKUP,
    backup_source: str = "/backup/xtrabackup/latest",
    dest_host: str | None = None,
    dest_port: int | None = None,
    database: str | None = None,
    service_host: str = "10.0.0.5",
    service_port: int = 3306,
    service_name: str = "mysql-prod",
    all_servers: dict[str, object] | None = None,
    alert_on_fail: bool = False,
) -> Task:
    """Build a legacy mysql restores task row without ``data['_form']``."""
    server_list_entry: dict[str, object] = {
        "ALIAS": "restore-job",
        "BACKUP_TYPE": backup_type.value,
        "BACKUP_SOURCE": backup_source,
    }
    if dest_host is not None:
        server_list_entry["DEST_HOST"] = dest_host
    if dest_port is not None:
        server_list_entry["DEST_PORT"] = dest_port
    if database is not None:
        server_list_entry["DATABASE"] = database
    return Task(
        name=name,
        data={
            "task": "run-python",
            "meta": {
                "target": target,
                CONNECTIVITY_META_HOST_KEY: service_host,
                CONNECTIVITY_META_PORT_KEY: service_port,
                "_service_name": service_name,
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [server_list_entry],
                        "ALL_SERVERS": all_servers or {},
                    }
                ),
            },
            "payload": "file://app/sep/apps/mysql_backups/restore/xtrabackup_payload",
        },
        backend=TaskBackendEnum.PROXY,
        owner="RESTORES",
        alert_on_fail=alert_on_fail,
    )


def test_reconstruct_mysql_restores_form_preserves_alert_on_fail():
    """Carry ``task.alert_on_fail`` into the reconstructed create body."""
    service_lookup, schema_lookup = _lookups()
    task = _legacy_restore_task(alert_on_fail=True)

    body = reconstruct_mysql_restores_form(task, _ctx(service_lookup, schema_lookup))

    assert body is not None
    assert body["alert_on_fail"] is True
    RestoreCreate.model_validate(body)


def test_reconstruct_mysql_restores_form_xtrabackup_happy_path():
    """Rebuild an XtraBackup restore body without destination service fields."""
    service_lookup, schema_lookup = _lookups()
    task = _legacy_restore_task(
        all_servers={"LOGGING_DIR": "/var/log/restore"},
    )

    body = reconstruct_mysql_restores_form(task, _ctx(service_lookup, schema_lookup))

    assert body is not None
    assert body["task_name"] == "mysql-restore-legacy"
    assert body["hostname"] == "executor-1"
    assert body["backup_type"] == BackupType.XTRABACKUP.value
    assert body["backup_source"] == "/backup/xtrabackup/latest"
    assert body["logging_dir"] == "/var/log/restore"
    assert "service_id" not in body
    assert "host" not in body
    assert "database" not in body
    RestoreCreate.model_validate(body)


def test_reconstruct_mysql_restores_form_mydumper_resolves_service_and_schema():
    """Resolve Mydumper destination service and database schema ids."""
    expected_service_id = 4
    expected_schema_id = 9
    service_lookup, schema_lookup = _lookups(
        _service(
            expected_service_id,
            name="mysql-prod",
            address="10.0.0.5",
            port=3306,
        ),
        schemas=(
            _schema(expected_schema_id, service_id=expected_service_id, name="appdb"),
        ),
    )
    task = _legacy_restore_task(
        backup_type=BackupType.MYDUMPER,
        backup_source="host.example.com:/backups/mydumper",
        dest_host="10.0.0.5",
        dest_port=3306,
        database="appdb",
        all_servers={"LOCAL_PATH": "/tmp/restore"},
    )

    body = reconstruct_mysql_restores_form(task, _ctx(service_lookup, schema_lookup))

    assert body is not None
    assert body["service_id"] == str(expected_service_id)
    assert body["schema_id"] == str(expected_schema_id)
    assert body["local_path"] == "/tmp/restore"
    RestoreCreate.model_validate(body)


def test_reconstruct_mysql_restores_form_binlog_happy_path():
    """Rebuild a Binlog restore body without destination service fields."""
    expected_start_position = 4
    service_lookup, schema_lookup = _lookups()
    task = _legacy_restore_task(
        backup_type=BackupType.BINLOG,
        backup_source="host.example.com:/backups/binlog",
        all_servers={
            "START_FILE": "binlog.0001",
            "START_POSITION": expected_start_position,
            "LOCAL_PATH": "/tmp/binlog-restore",
            "BINLOG_RESTORE_EXTRA_ARGS": "--verbose",
        },
    )

    body = reconstruct_mysql_restores_form(task, _ctx(service_lookup, schema_lookup))

    assert body is not None
    assert body["backup_type"] == BackupType.BINLOG.value
    assert body["backup_source"] == "host.example.com:/backups/binlog"
    assert body["start_file"] == "binlog.0001"
    assert body["start_position"] == expected_start_position
    assert body["local_path"] == "/tmp/binlog-restore"
    assert body["binlog_restore_extra_args"] == "--verbose"
    assert "service_id" not in body
    RestoreCreate.model_validate(body)


def test_reconstruct_mysql_restores_form_mydumper_omits_schema_id_when_ambiguous():
    """Keep Mydumper restores when schema resolution is ambiguous."""
    expected_service_id = 4
    service_lookup, schema_lookup = _lookups(
        _service(
            expected_service_id,
            name="mysql-prod",
            address="10.0.0.5",
            port=3306,
        ),
        schemas=(
            _schema(1, service_id=expected_service_id, name="appdb"),
            _schema(2, service_id=expected_service_id, name="appdb"),
        ),
    )
    task = _legacy_restore_task(
        backup_type=BackupType.MYDUMPER,
        backup_source="host.example.com:/backups/mydumper",
        dest_host="10.0.0.5",
        dest_port=3306,
        database="appdb",
    )

    body = reconstruct_mysql_restores_form(task, _ctx(service_lookup, schema_lookup))

    assert body is not None
    assert body["service_id"] == str(expected_service_id)
    assert "schema_id" not in body
    RestoreCreate.model_validate(body)


def test_reconstruct_mysql_restores_form_mydumper_ignores_service_name_when_dest_host_set():
    """Resolve Mydumper destination by host/port, not ``meta['_service_name']``."""
    service_lookup, schema_lookup = _lookups(
        _service(1, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_restore_task(
        backup_type=BackupType.MYDUMPER,
        backup_source="host.example.com:/backups/mydumper",
        dest_host="10.0.0.9",
        dest_port=3306,
        service_name="mysql-prod",
    )

    assert (
        reconstruct_mysql_restores_form(task, _ctx(service_lookup, schema_lookup))
        is None
    )


def test_reconstruct_mysql_restores_form_returns_none_for_mydumper_without_service():
    """Skip Mydumper tasks whose destination host cannot be matched in inventory."""
    service_lookup, schema_lookup = _lookups(
        _service(1, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_restore_task(
        backup_type=BackupType.MYDUMPER,
        backup_source="host.example.com:/backups/mydumper",
        dest_host="10.0.0.9",
        dest_port=3306,
    )

    assert (
        reconstruct_mysql_restores_form(task, _ctx(service_lookup, schema_lookup))
        is None
    )


def test_reconstruct_mysql_restores_form_returns_none_when_not_run_python():
    """Skip tasks that are not ``run-python`` restore rows."""
    service_lookup, schema_lookup = _lookups()
    task = _legacy_restore_task()
    task.data["task"] = "run-command"

    assert (
        reconstruct_mysql_restores_form(task, _ctx(service_lookup, schema_lookup))
        is None
    )


def test_backfill_single_task_stamps_mysql_restores_form():
    """Run the orchestrator pipeline for a reconstructable mysql restores task."""
    expected_service_id = 12
    service_lookup, schema_lookup = _lookups(
        _service(
            expected_service_id,
            name="mysql-prod",
            address="10.0.0.5",
            port=3306,
        ),
    )
    task = _legacy_restore_task(
        name="restore-stamp",
        backup_type=BackupType.MYDUMPER,
        backup_source="host.example.com:/backups/mydumper",
        dest_host="10.0.0.5",
        dest_port=3306,
        alert_on_fail=True,
    )
    entry = FORM_BACKFILL_ENTRY
    ctx = FormBackfillContext(
        log=__import__("logging").getLogger("test"),
        service_lookup=service_lookup,
        schema_lookup=schema_lookup,
    )

    outcome = _backfill_single_task(task, entry, ctx)

    assert outcome.label == "stamped"
    assert outcome.stamped_data is not None
    stamped_form = outcome.stamped_data[RESERVED_FORM_KEY]
    assert stamped_form["task_name"] == "restore-stamp"
    assert stamped_form["service_id"] == str(expected_service_id)
    assert stamped_form["backup_type"] == BackupType.MYDUMPER.value
    assert stamped_form["backup_source"] == "host.example.com:/backups/mydumper"
    assert stamped_form["alert_on_fail"] is True


def _stamped_restore_task(stored_form: dict, *, name: str = "restore-stamped") -> Task:
    """Build a restore task row already carrying a ``data['_form']`` stamp."""
    task = _legacy_restore_task(name=name)
    task.data[RESERVED_FORM_KEY] = stored_form
    return task


def _pre_declaration_stamp(**overrides: object) -> dict:
    """Return a stamp as it was written before the source controls existed."""
    stamp = {
        "task_name": "restore-stamped",
        "hostname": "executor-1",
        "backup_type": BackupType.MYDUMPER.value,
        "backup_source": "/backups/mydumper/latest",
        "service_id": "12",
        "ssh_user": legacy_default("ssh_user"),
        "ssh_port": legacy_default("ssh_port"),
        "s3_tool": legacy_default("s3_tool"),
    }
    stamp.update(overrides)
    return stamp


def test_repair_declares_the_source_and_strips_what_it_forbids():
    """Declare the source on a pre-declaration stamp so the gates accept it."""
    service_lookup, schema_lookup = _lookups(
        _service(12, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _stamped_restore_task(_pre_declaration_stamp())

    outcome = _backfill_single_task(
        task, FORM_BACKFILL_ENTRY, _ctx(service_lookup, schema_lookup)
    )

    assert outcome.label == "repaired"
    assert outcome.stamped_data is not None
    repaired = outcome.stamped_data[RESERVED_FORM_KEY]
    assert repaired["source_transport"] == SourceTransport.LOCAL.value
    assert repaired["ssh_user"] is None
    assert repaired["ssh_port"] is None
    assert repaired["s3_tool"] is None


def test_repair_keeps_credentials_the_inferred_transport_can_use():
    """Keep a non-default SSH credential and infer the transport that consumes it."""
    service_lookup, schema_lookup = _lookups(
        _service(12, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _stamped_restore_task(
        _pre_declaration_stamp(ssh_user="deploy", ssh_key="prod-key")
    )

    outcome = _backfill_single_task(
        task, FORM_BACKFILL_ENTRY, _ctx(service_lookup, schema_lookup)
    )

    assert outcome.label == "repaired"
    assert outcome.stamped_data is not None
    repaired = outcome.stamped_data[RESERVED_FORM_KEY]
    assert repaired["source_transport"] == SourceTransport.SSH.value
    assert repaired["ssh_user"] == "deploy"
    assert repaired["ssh_key"] == "prod-key"


def test_repair_skips_a_stamp_that_already_declares_its_source():
    """Leave an operator's own declaration untouched."""
    service_lookup, schema_lookup = _lookups(
        _service(12, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _stamped_restore_task(
        {
            "task_name": "restore-stamped",
            "hostname": "executor-1",
            "backup_type": BackupType.MYDUMPER.value,
            "backup_source": "/backups/mydumper/latest",
            "source_transport": SourceTransport.LOCAL.value,
        }
    )

    outcome = _backfill_single_task(
        task, FORM_BACKFILL_ENTRY, _ctx(service_lookup, schema_lookup)
    )

    assert outcome.label == "skipped_existing"
    assert outcome.stamped_data is None


def test_reconstructed_legacy_body_declares_a_source_the_gates_accept():
    """Return a legacy-reconstructed body that validates against the new gates."""
    service_lookup, schema_lookup = _lookups(
        _service(12, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_restore_task(
        backup_type=BackupType.MYDUMPER,
        backup_source="db01:/backups/mydumper",
        dest_host="10.0.0.5",
        dest_port=3306,
        all_servers={"SSH_USER": "percona", "SSH_PORT": 22, "S3_TOOL": "s3cmd"},
    )

    body = reconstruct_mysql_restores_form(task, _ctx(service_lookup, schema_lookup))

    assert body is not None
    assert body["source_transport"] == SourceTransport.SSH.value
    RestoreCreate.model_validate(body)


def test_reconstruction_accepts_a_replication_option_with_the_toggle_off():
    """Accept the combination the create form started rejecting when it nested.

    Nesting the replication options under ``slave_from_master`` put a
    ``Forbidden`` gate on each, because the ``Ui(parent=...)`` pointer is
    presentation only and the server has to enforce the pairing itself. A stored
    config carries them independently, so without the leniency a restore that
    recorded a replication source while replication was off would be skipped —
    and a task with no ``_form`` stamp has no Edit affordance at all.
    """
    body = {
        "task_name": "restore-legacy",
        "hostname": "executor-host",
        "backup_type": BackupType.XTRABACKUP.value,
        "backup_source": "/data/backups/latest",
        "slave_from_master": False,
        "master_ip": "10.0.0.9",
        "master_user": "repl",
        "master_password": "secret",
        "wait_for_catchup": True,
    }

    legacy = LegacyRestoreCreate.model_validate(body)
    assert legacy.master_ip == "10.0.0.9"
    assert legacy.wait_for_catchup is True

    with pytest.raises(ValidationError) as excinfo:
        RestoreCreate.model_validate(body)
    assert "'slave_from_master' must be enabled" in str(excinfo.value)


_DEFAULT_MASTER_PORT = 3306


def test_master_port_default_survives_replication_being_off():
    """Keep ``master_port`` out of the parented set.

    It defaults to 3306 and is read when 'Restore my.cnf' is set, not when
    replication starts, so gating it on ``slave_from_master`` would reject every
    restore that leaves replication off — the common case.
    """
    created = RestoreCreate.model_validate(
        {
            "task_name": "restore",
            "hostname": "executor-host",
            "backup_type": BackupType.XTRABACKUP.value,
            "backup_source": "/data/backups/latest",
        }
    )
    assert created.slave_from_master is False
    assert created.master_port == _DEFAULT_MASTER_PORT
