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

"""Tests for the mysql_backups legacy form reconstructor."""

from types import SimpleNamespace

import yaml

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.form_backfill import (
    _backfill_single_task,
    _BackfillApp,
    FormBackfillContext,
)
from app.sep.apps.framework.form_backfill_inventory import ServiceIdLookup
from app.sep.apps.framework.spec import RESERVED_FORM_KEY
from app.sep.apps.mysql_backups.app import app as mysql_backups_app
from app.sep.apps.mysql_backups.form_backfill import (
    _extract_upload_from_meta,
    reconstruct_mysql_backups_form,
)
from app.sep.apps.mysql_backups.models import BackupCreate, BackupType
from app.sep.connectivity import CONNECTIVITY_META_HOST_KEY, CONNECTIVITY_META_PORT_KEY
from app.tasks.models import Task, TaskBackendEnum


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


def _lookup(*services: SimpleNamespace) -> ServiceIdLookup:
    """Build a lookup table from the supplied service records."""
    return ServiceIdLookup.from_services(services)


def _ctx(lookup: ServiceIdLookup) -> FormBackfillContext:
    """Return a backfill context wired to ``lookup``."""
    return FormBackfillContext(
        log=__import__("logging").getLogger("test"), service_lookup=lookup
    )


def _legacy_mysql_backup_task(
    *,
    name: str = "mysql-backup-legacy",
    target: str = "executor-1",
    alias: str = "db1-mysql",
    service_host: str = "10.0.0.5",
    service_port: int = 3306,
    service_name: str = "mysql-prod",
    backup_type: BackupType = BackupType.XTRABACKUP,
    upload: list[str] | None = None,
    all_servers: dict[str, object] | None = None,
    alert_on_fail: bool = False,
) -> Task:
    """Build a legacy mysql_backups task row without ``data['_form']``."""
    server_list_entry: dict[str, object] = {
        "ALIAS": alias,
        "HOST": service_host,
        "PORT": service_port,
        "BACKUP_TYPE": backup_type.value,
    }
    if upload is not None:
        server_list_entry["UPLOAD"] = upload
    all_servers_config = all_servers or {}
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
                        "ALL_SERVERS": all_servers_config,
                    }
                ),
            },
            "payload": "file://app/sep/apps/mysql_backups/payload",
        },
        backend=TaskBackendEnum.PROXY,
        owner="BACKUPS",
        alert_on_fail=alert_on_fail,
    )


def test_extract_upload_from_meta_normalizes_providers():
    """Normalize mixed-case upload provider names from persisted YAML."""
    meta = {
        "config": yaml.dump(
            {
                "SERVER_LIST": [
                    {
                        "HOST": "10.0.0.5",
                        "BACKUP_TYPE": BackupType.BINLOG.value,
                        "UPLOAD": ["gsutil", "S3"],
                    }
                ]
            }
        )
    }

    assert _extract_upload_from_meta(meta) == ["gsutil", "s3"]


def test_reconstruct_mysql_backups_form_happy_path():
    """Rebuild a create body and omit parse-only keys."""
    expected_service_id = 7
    lookup = _lookup(
        _service(
            expected_service_id,
            name="mysql-prod",
            address="10.0.0.5",
            port=3306,
        ),
    )
    task = _legacy_mysql_backup_task(
        upload=["S3"],
        all_servers={
            "S3_BUCKET": "my-bucket",
            "XTRABACKUP_QUIET": True,
            "BACKUP_DIR": "/backup",
        },
        alert_on_fail=True,
    )

    body = reconstruct_mysql_backups_form(task, _ctx(lookup))

    assert body is not None
    assert body["task_name"] == "mysql-backup-legacy"
    assert body["hostname"] == "executor-1"
    assert body["service_id"] == expected_service_id
    assert body["backup_type"] == BackupType.XTRABACKUP.value
    assert body["alias"] == "db1-mysql"
    assert body["upload"] == ["s3"]
    assert body["s3_bucket"] == "my-bucket"
    assert body["xtrabackup_quiet"] is True
    assert body["backup_dir"] == "/backup"
    assert body["alert_on_fail"] is True
    assert "host" not in body
    assert "port" not in body
    assert "name" not in body
    BackupCreate.model_validate(body)


def test_reconstruct_mysql_backups_form_binlog_alternative_host():
    """Round-trip binlog-specific fields from persisted YAML."""
    expected_service_id = 2
    lookup = _lookup(
        _service(
            expected_service_id,
            name="mysql-prod",
            address="10.0.0.5",
            port=3306,
        ),
    )
    task = _legacy_mysql_backup_task(
        backup_type=BackupType.BINLOG,
        upload=["GSUTIL"],
        all_servers={
            "BINLOG_ALTERNATIVE_HOST": "10.0.0.9",
            "BINLOG_PREFIX": "binlog",
            "GS_BUCKET": "gs-bucket",
        },
    )

    body = reconstruct_mysql_backups_form(task, _ctx(lookup))

    assert body is not None
    assert body["backup_type"] == BackupType.BINLOG.value
    assert body["binlog_alternative_host"] == "10.0.0.9"
    assert body["binlog_prefix"] == "binlog"
    assert body["gs_bucket"] == "gs-bucket"
    assert body["upload"] == ["gsutil"]
    BackupCreate.model_validate(body)


def test_reconstruct_mysql_backups_form_mydumper_happy_path():
    """Round-trip mydumper-specific fields from persisted YAML."""
    expected_service_id = 3
    lookup = _lookup(
        _service(
            expected_service_id,
            name="mysql-prod",
            address="10.0.0.5",
            port=3306,
        ),
    )
    task = _legacy_mysql_backup_task(
        backup_type=BackupType.MYDUMPER,
        upload=["GSUTIL"],
        all_servers={
            "MYDUMPER_VERBOSE": 1,
            "MYDUMPER_EXTRA_ARGS": "--foo",
            "GS_BUCKET": "gs-bucket",
        },
    )

    body = reconstruct_mysql_backups_form(task, _ctx(lookup))

    assert body is not None
    assert body["backup_type"] == BackupType.MYDUMPER.value
    assert body["mydumper_verbose"] == 1
    assert body["mydumper_extra_args"] == "--foo"
    assert body["gs_bucket"] == "gs-bucket"
    assert body["upload"] == ["gsutil"]
    BackupCreate.model_validate(body)


def test_reconstruct_mysql_backups_form_returns_none_when_not_run_python():
    """Skip tasks that are not ``run-python`` backup rows."""
    lookup = _lookup(
        _service(1, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_mysql_backup_task()
    task.data["task"] = "run-command"

    assert reconstruct_mysql_backups_form(task, _ctx(lookup)) is None


def test_reconstruct_mysql_backups_form_returns_none_when_service_unresolved():
    """Skip tasks whose database host cannot be matched in inventory."""
    lookup = _lookup(
        _service(1, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_mysql_backup_task(
        service_host="10.0.0.9",
        service_name="unknown-service",
        upload=["S3"],
        all_servers={"S3_BUCKET": "bucket"},
    )

    assert reconstruct_mysql_backups_form(task, _ctx(lookup)) is None


def test_backfill_single_task_stamps_mysql_backups_form():
    """Run the orchestrator pipeline for a reconstructable mysql_backups task."""
    expected_service_id = 9
    lookup = _lookup(
        _service(
            expected_service_id,
            name="mysql-prod",
            address="10.0.0.5",
            port=3306,
        ),
    )
    task = _legacy_mysql_backup_task(
        name="mysql-stamp",
        upload=["RSYNC"],
        all_servers={"RSYNC_PATH": "/remote/backups"},
    )
    entry = _BackfillApp(
        app=mysql_backups_app, reconstructor=reconstruct_mysql_backups_form
    )
    ctx = FormBackfillContext(
        log=__import__("logging").getLogger("test"),
        service_lookup=lookup,
    )

    outcome = _backfill_single_task(task, entry, ctx)

    assert outcome.label == "stamped"
    assert outcome.stamped_data is not None
    stamped_form = outcome.stamped_data[RESERVED_FORM_KEY]
    assert stamped_form["task_name"] == "mysql-stamp"
    assert stamped_form["service_id"] == expected_service_id
    assert stamped_form["backup_type"] == BackupType.XTRABACKUP.value
    assert stamped_form["upload"] == ["rsync"]
    assert stamped_form["rsync_path"] == "/remote/backups"
