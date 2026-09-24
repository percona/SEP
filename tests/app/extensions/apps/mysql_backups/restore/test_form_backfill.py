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

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

import app.extensions.apps.mysql_backups.restore.form_backfill as restore_form_backfill
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.extensions.apps.framework.form_backfill import _backfill_single_task
from app.extensions.apps.framework.form_backfill_inventory import (
    SchemaIdLookup,
    ServiceIdLookup,
)
from app.extensions.apps.framework.form_backfill_registry import FormBackfillContext
from app.extensions.apps.framework.spec import RESERVED_FORM_KEY
from app.extensions.apps.mysql_backups.crud import MysqlBackupRunManager
from app.extensions.apps.mysql_backups.forms import EncryptionFormat
from app.extensions.apps.mysql_backups.models import (
    BackupType,
    CataloguedSourceTransport,
    MysqlBackupRun,
)
from app.extensions.apps.mysql_backups.restore.form_backfill import (
    _sync_catalogued_transport_for_stamp,
    CATALOG_TRANSPORTS_EXTRA,
    FORM_BACKFILL_ENTRY,
    reconstruct_mysql_restores_form,
)
from app.extensions.apps.mysql_backups.restore.models import (
    RestoreCreate,
    SourceTransport,
)
from app.extensions.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
)
from app.inventory.models import ServiceTypeEnum
from app.tasks.models import Task, TaskBackendEnum
from tests.app.db_schema import apply_schema
from tests.app.extensions.apps.mysql_backups.restore.conftest import legacy_default


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
    server_extra: dict[str, object] | None = None,
    alert_on_fail: bool = False,
) -> Task:
    """Build a legacy mysql restores task row without ``data['_form']``."""
    server_list_entry: dict[str, object] = {
        "ALIAS": "restore-job",
        "BACKUP_TYPE": backup_type.value,
        "BACKUP_SOURCE": backup_source,
        **(server_extra or {}),
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
            "payload": "file://app/extensions/apps/mysql_backups/restore/xtrabackup_payload",
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
    """Leave a stamp that already describes its own source untouched.

    Both halves have to be present for the stamp to need nothing: a stamp naming
    only its transport is still owed the encryption the edit form reads.
    """
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
            "source_encryption": EncryptionFormat.NONE.value,
        }
    )

    outcome = _backfill_single_task(
        task, FORM_BACKFILL_ENTRY, _ctx(service_lookup, schema_lookup)
    )

    assert outcome.label == "skipped_existing"
    assert outcome.stamped_data is None


class TestRepairCatalogTransport:
    """Cover catalogued S3/GCS seeding on stamp repair."""

    def test_prefers_catalogued_object_store_transport(self):
        """Seed S3 from the batched prefetch when repairing a stamp that would infer local."""
        service_lookup, schema_lookup = _lookups(
            _service(12, name="mysql-prod", address="10.0.0.5", port=3306),
        )
        stamp = _pre_declaration_stamp()
        task = _stamped_restore_task(stamp)
        ctx = _ctx(service_lookup, schema_lookup)
        ctx.extras[CATALOG_TRANSPORTS_EXTRA] = {
            (
                12,
                "mysql-prod",
                "/backups/mydumper/latest",
            ): CataloguedSourceTransport.S3,
        }

        outcome = _backfill_single_task(task, FORM_BACKFILL_ENTRY, ctx)

        assert outcome.label == "repaired"
        assert outcome.stamped_data is not None
        repaired = outcome.stamped_data[RESERVED_FORM_KEY]
        assert repaired["source_transport"] == SourceTransport.S3.value

    def test_skips_catalog_lookup_when_source_already_declared(
        self, mocker: MockerFixture
    ):
        """Do not evaluate the catalog lookup for a stamp that already declares transport.

        ``repair_source_declaration`` would ignore a hit anyway; skipping the call
        avoids the sync bridge (and even a prefetch map hit) on the eager argument.
        """
        lookup = mocker.patch(
            "app.extensions.apps.mysql_backups.restore.form_backfill.catalogued_transport_for_stamp",
        )
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
                "source_encryption": EncryptionFormat.NONE.value,
            }
        )

        outcome = _backfill_single_task(
            task, FORM_BACKFILL_ENTRY, _ctx(service_lookup, schema_lookup)
        )

        assert outcome.label == "skipped_existing"
        lookup.assert_not_called()


@pytest.mark.asyncio
async def test_catalogued_transport_bridges_under_a_running_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the NullPool sync bridge while a request loop is already running.

    Prefetch-``context`` tests never enter ``_run_coro_sync`` /
    ``_fetch_catalogued_transport``. A context-less call under pytest-asyncio is
    the real cross-loop path: worker thread + ``asyncio.run`` + throwaway
    ``NullPool`` engine against the sep URL.
    """
    db_path = tmp_path / "catalog.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    seed_engine = create_async_engine(url, json_serializer=json_serializer)
    try:
        async with seed_engine.begin() as conn:
            await apply_schema(conn, SQLModel.metadata)
        async with get_async_session_maker_from_engine(seed_engine)() as session:
            await MysqlBackupRunManager.save(
                session,
                MysqlBackupRun(
                    task_history_id=1,
                    service_name="svc-a",
                    service_id=7,
                    backup_type="M",
                    # Local preferred source so inference alone would stay LOCAL;
                    # the catalogued S3 value is what must win through the bridge.
                    location="/backups/mydumper/latest",
                    source_transport=CataloguedSourceTransport.S3,
                ),
            )
    finally:
        await seed_engine.dispose()

    monkeypatch.setattr(
        restore_form_backfill, "extensions_engine", SimpleNamespace(url=url)
    )
    create_kwargs: list[dict] = []
    real_create = restore_form_backfill.create_async_engine

    def _tracking_create(*args: object, **kwargs: object):
        create_kwargs.append(kwargs)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(restore_form_backfill, "create_async_engine", _tracking_create)

    stored_form = {
        "task_name": "restore-task",
        "hostname": "executor-1",
        "backup_type": BackupType.MYDUMPER.value,
        "service_id": "7",
        "backup_source": "/backups/mydumper/latest",
        "s3_tool": "s3cmd",
    }
    task = _stamped_restore_task(stored_form)

    assert (
        _sync_catalogued_transport_for_stamp(task, stored_form)
        == CataloguedSourceTransport.S3
    )
    assert create_kwargs
    assert all(call.get("poolclass") is NullPool for call in create_kwargs)


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


def test_reconstructed_body_declares_the_aes_format_of_a_stored_key_file():
    """Declare AES-256 for a restore whose config names a key file.

    The key file is what the restore decrypts with, so the reconstructed body has
    to name the format that admits it rather than leave it for the gate to reject.
    """
    service_lookup, schema_lookup = _lookups(
        _service(12, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_restore_task(
        backup_type=BackupType.MYDUMPER,
        dest_host="10.0.0.5",
        dest_port=3306,
        server_extra={"XTRABACKUP_AES256_KEYFILE": "/etc/xb/aes.key"},
    )

    body = reconstruct_mysql_restores_form(task, _ctx(service_lookup, schema_lookup))

    assert body is not None
    assert body["source_encryption"] == EncryptionFormat.AES256
    assert body["xtrabackup_aes256_keyfile"] == "/etc/xb/aes.key"
    RestoreCreate.model_validate(body)
