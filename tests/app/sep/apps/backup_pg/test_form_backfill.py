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

"""Tests for the backup_pg legacy form reconstructor."""

from types import SimpleNamespace

import yaml

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_pg.form_backfill import (
    _extract_stanza_from_meta,
    FORM_BACKFILL_ENTRIES,
    reconstruct_backup_pg_form,
)
from app.sep.apps.backup_pg.models import BackupPgForm, BackupType
from app.sep.apps.framework.form_backfill import _backfill_single_task
from app.sep.apps.framework.form_backfill_inventory import ServiceIdLookup
from app.sep.apps.framework.form_backfill_registry import FormBackfillContext
from app.sep.apps.framework.spec import RESERVED_FORM_KEY
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
        type=ServiceTypeEnum.POSTGRESQL,
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


def _legacy_backup_pg_task(
    *,
    name: str = "pg-backup-legacy",
    target: str = "executor-1",
    stanza: str = "sep-test",
    service_host: str = "db.internal",
    service_port: int = 5432,
    service_name: str = "pg-prod",
    backup_dir: str = "/var/lib/pgbackrest",
    logging_dir: str | None = "/var/log/pgbackrest",
    alert_on_fail: bool = False,
) -> Task:
    """Build a legacy backup_pg task row without ``data['_form']``."""
    all_servers: dict[str, object] = {"BACKUP_DIR": backup_dir}
    if logging_dir is not None:
        all_servers["LOGGING_DIR"] = logging_dir
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
                        "SERVER_LIST": [
                            {
                                "ALIAS": stanza,
                                "HOST": "localhost",
                                "PORT": service_port,
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ],
                        "ALL_SERVERS": all_servers,
                    }
                ),
            },
            "payload": "file://app/sep/apps/backup_pg/payload",
        },
        backend=TaskBackendEnum.PROXY,
        owner="BACKUP_PG",
        alert_on_fail=alert_on_fail,
    )


def test_extract_stanza_from_meta_reads_server_list_alias():
    """Read the stanza from the first ``SERVER_LIST`` entry."""
    expected_stanza = "prod-main"
    assert (
        _extract_stanza_from_meta(
            {
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "ALIAS": expected_stanza,
                                "HOST": "localhost",
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ]
                    }
                )
            }
        )
        == expected_stanza
    )


def test_reconstruct_backup_pg_form_happy_path():
    """Rebuild a create body and omit forbidden parse keys."""
    expected_service_id = 11
    lookup = _lookup(
        _service(
            expected_service_id,
            name="pg-prod",
            address="db.internal",
            port=5432,
        ),
    )
    task = _legacy_backup_pg_task(alert_on_fail=True)

    body = reconstruct_backup_pg_form(task, _ctx(lookup))

    assert body == {
        "task_name": "pg-backup-legacy",
        "hostname": "executor-1",
        "service_id": expected_service_id,
        "stanza": "sep-test",
        "backup_dir": "/var/lib/pgbackrest",
        "logging_dir": "/var/log/pgbackrest",
        "alert_on_fail": True,
    }
    BackupPgForm.model_validate(body)


def test_reconstruct_backup_pg_form_strips_upload_targets():
    """Drop upload-target keys that ``BackupPgForm`` forbids via ``extra='forbid'``."""
    expected_service_id = 3
    lookup = _lookup(
        _service(
            expected_service_id,
            name="pg-prod",
            address="db.internal",
            port=5432,
        ),
    )
    task = _legacy_backup_pg_task()
    config = yaml.safe_load(task.data["meta"]["config"])
    config["SERVER_LIST"][0]["UPLOAD"] = ["S3"]
    config["ALL_SERVERS"].update(
        {
            "S3_BUCKET": "my-bucket",
            "S3_STORAGE_CLASS": "STANDARD_IA",
            "SKIP_S3_SAFETY_CHECK": True,
        }
    )
    task.data["meta"]["config"] = yaml.dump(config)

    body = reconstruct_backup_pg_form(task, _ctx(lookup))

    assert body is not None
    assert "s3_bucket" not in body
    assert "host" not in body
    assert "port" not in body
    assert "backup_type" not in body
    BackupPgForm.model_validate(body)


def test_reconstruct_backup_pg_form_returns_none_without_stanza():
    """Skip tasks whose YAML config omits ``SERVER_LIST[0].ALIAS``."""
    lookup = _lookup(
        _service(1, name="pg-prod", address="db.internal", port=5432),
    )
    task = _legacy_backup_pg_task()
    config = yaml.safe_load(task.data["meta"]["config"])
    del config["SERVER_LIST"][0]["ALIAS"]
    task.data["meta"]["config"] = yaml.dump(config)

    assert reconstruct_backup_pg_form(task, _ctx(lookup)) is None


def test_reconstruct_backup_pg_form_returns_none_when_service_unresolved():
    """Skip tasks whose database host cannot be matched in inventory."""
    lookup = _lookup(
        _service(1, name="pg-prod", address="db.internal", port=5432),
    )
    task = _legacy_backup_pg_task(
        service_host="10.0.0.9",
        service_name="unknown-service",
    )

    assert reconstruct_backup_pg_form(task, _ctx(lookup)) is None


def test_reconstruct_backup_pg_form_returns_none_when_not_run_python():
    """Skip tasks that are not ``run-python`` backup_pg rows."""
    lookup = _lookup(
        _service(1, name="pg-prod", address="db.internal", port=5432),
    )
    task = _legacy_backup_pg_task()
    task.data["task"] = "run-command"

    assert reconstruct_backup_pg_form(task, _ctx(lookup)) is None


def test_backfill_single_task_stamps_backup_pg_form():
    """Run the orchestrator pipeline for a reconstructable backup_pg task."""
    expected_service_id = 5
    lookup = _lookup(
        _service(
            expected_service_id,
            name="pg-prod",
            address="db.internal",
            port=5432,
        ),
    )
    task = _legacy_backup_pg_task(name="pg-stamp", stanza="prod-main")
    entry = FORM_BACKFILL_ENTRIES[0]
    ctx = FormBackfillContext(
        log=__import__("logging").getLogger("test"),
        service_lookup=lookup,
    )

    outcome = _backfill_single_task(task, entry, ctx)

    assert outcome.label == "stamped"
    assert outcome.stamped_data is not None
    stamped_form = outcome.stamped_data[RESERVED_FORM_KEY]
    assert stamped_form["task_name"] == "pg-stamp"
    assert stamped_form["service_id"] == expected_service_id
    assert stamped_form["stanza"] == "prod-main"
    assert stamped_form["backup_dir"] == "/var/lib/pgbackrest"


def test_backfill_single_task_skips_invalid_incremental_cycle():
    """Count a legacy out-of-vocabulary cycle as ``skipped_invalid``, not an error."""
    lookup = _lookup(
        _service(9, name="pg-prod", address="db.internal", port=5432),
    )
    task = _legacy_backup_pg_task(name="pg-bad-cycle")
    config = yaml.safe_load(task.data["meta"]["config"])
    config["ALL_SERVERS"]["PGBACKREST_INCREMENTAL_CYCLE"] = "monday"
    task.data["meta"]["config"] = yaml.dump(config)
    entry = FORM_BACKFILL_ENTRIES[0]
    ctx = _ctx(lookup)

    outcome = _backfill_single_task(task, entry, ctx)

    assert outcome.label == "skipped_invalid"
    assert outcome.stamped_data is None
