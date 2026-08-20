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

"""Tests for the archives legacy form reconstructor."""

from types import SimpleNamespace

import yaml

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.archives.constants import SwapDropEnum
from app.sep.apps.archives.form_backfill import (
    _load_archives_config,
    FORM_BACKFILL_ENTRIES,
    reconstruct_archives_form,
)
from app.sep.apps.archives.models import ArchivesCreate
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


def _legacy_archives_task(
    *,
    name: str = "arch-1",
    target: str = "executor-host",
    source_host: str = "src-host",
    source_port: int = 3306,
    service_name: str = "src-svc",
    purge_item: dict[str, object],
    alert_on_fail: bool = False,
) -> Task:
    """Build a legacy archives task row without ``data['_form']``."""
    config = {
        "ALL": {"SOURCE_HOST": source_host, "SOURCE_PORT": source_port},
        "PURGE_LIST": [purge_item],
    }
    return Task(
        name=name,
        data={
            "task": "run-python",
            "meta": {
                "target": target,
                CONNECTIVITY_META_HOST_KEY: source_host,
                CONNECTIVITY_META_PORT_KEY: source_port,
                "_service_name": service_name,
                "config": yaml.dump(config),
            },
            "payload": "file://app/sep/apps/archives/payload",
        },
        backend=TaskBackendEnum.PROXY,
        owner="ARCHIVER",
        alert_on_fail=alert_on_fail,
    )


def test_load_archives_config_reads_all_and_first_purge_entry():
    """Parse ``ALL`` and the first ``PURGE_LIST`` entry from archiver YAML."""
    config_yaml = yaml.dump(
        {
            "ALL": {"SOURCE_HOST": "db.internal", "SOURCE_PORT": 3306},
            "PURGE_LIST": [
                {
                    "ALIAS": "arch-a",
                    "SOURCE_DB": "app",
                    "SOURCE_TABLE": "events",
                    "DEST_TABLE": "archive",
                    "SWAP_DROP": 0,
                    "WHERE": "id < 1",
                }
            ],
        }
    )

    loaded = _load_archives_config(config_yaml)

    assert loaded is not None
    all_section, purge_item = loaded
    assert _case_insensitive_get(all_section, "source_host") == "db.internal"
    assert _case_insensitive_get(purge_item, "source_table") == "events"


def _case_insensitive_get(mapping: dict[str, object], key: str) -> object:
    """Mirror the reconstructor's case-insensitive key lookup for assertions."""
    for candidate, value in mapping.items():
        if isinstance(candidate, str) and candidate.upper() == key.upper():
            return value
    return mapping.get(key)


def test_reconstruct_archives_form_table_to_table_same_host():
    """Rebuild a same-host table-to-table purge body."""
    expected_service_id = 7
    lookup = _lookup(
        _service(
            expected_service_id,
            name="src-svc",
            address="src-host",
            port=3306,
        ),
    )
    task = _legacy_archives_task(
        purge_item={
            "ALIAS": "arch-1",
            "SOURCE_DB": "src_db",
            "SOURCE_TABLE": "src_table",
            "DEST_TABLE": "dst_table",
            "SWAP_DROP": SwapDropEnum.PURGE_ONLY.value,
            "WHERE": "id < 100",
        },
    )

    body = reconstruct_archives_form(task, _ctx(lookup))

    assert body == {
        "task_name": "arch-1",
        "hostname": "executor-host",
        "service_id": expected_service_id,
        "swap_drop": SwapDropEnum.PURGE_ONLY.value,
        "source": {
            "mode": "table",
            "source_db": "src_db",
            "source_table": "src_table",
        },
        "destination": {"mode": "table", "dest_table": "dst_table"},
        "where": "id < 100",
        "alert_on_fail": False,
    }
    ArchivesCreate.model_validate(body)


def test_reconstruct_archives_form_table_to_file():
    """Rebuild a table-to-file purge body and map integer flags to bools."""
    lookup = _lookup(
        _service(2, name="src-svc", address="src-host", port=3306),
    )
    task = _legacy_archives_task(
        name="arch-2",
        purge_item={
            "ALIAS": "arch-2",
            "SOURCE_DB": "src_db",
            "SOURCE_TABLE": "src_table",
            "DEST_FILE": "/data/out.csv",
            "DISABLE_BULK_INSERT": 1,
            "SWAP_DROP": 0,
            "WHERE": "id < 100",
        },
    )

    body = reconstruct_archives_form(task, _ctx(lookup))

    assert body is not None
    assert body["destination"] == {"mode": "file", "dest_file": "/data/out.csv"}
    assert body["disable_bulk_insert"] is True
    ArchivesCreate.model_validate(body)


def test_reconstruct_archives_form_query_to_table_with_dest_db():
    """Rebuild a query-source purge with an explicit destination schema."""
    lookup = _lookup(
        _service(3, name="src-svc", address="src-host", port=3306),
    )
    task = _legacy_archives_task(
        name="arch-3",
        purge_item={
            "ALIAS": "arch-3",
            "SOURCE_QUERY": "SELECT * FROM t",
            "DEST_DB": "dst_db",
            "DEST_TABLE": "dst_table",
            "SWAP_DROP": 0,
            "WHERE": "id < 100",
        },
    )

    body = reconstruct_archives_form(task, _ctx(lookup))

    assert body is not None
    assert body["source"] == {"mode": "query", "source_query": "SELECT * FROM t"}
    assert body["destination"] == {
        "mode": "table",
        "dest_db": "dst_db",
        "dest_table": "dst_table",
    }
    ArchivesCreate.model_validate(body)


def test_reconstruct_archives_form_delete_data_without_destination():
    """Rebuild a delete-only purge body with no destination one-of."""
    lookup = _lookup(
        _service(4, name="src-svc", address="src-host", port=3306),
    )
    task = _legacy_archives_task(
        name="arch-6",
        purge_item={
            "ALIAS": "arch-6",
            "DELETE_DATA": 1,
            "SOURCE_DB": "src_db",
            "SOURCE_TABLE": "src_table",
            "SWAP_DROP": 0,
            "WHERE": "id < 100",
        },
    )

    body = reconstruct_archives_form(task, _ctx(lookup))

    assert body is not None
    assert "destination" not in body
    assert body["delete_data"] is True
    ArchivesCreate.model_validate(body)


def test_reconstruct_archives_form_manual_destination_host():
    """Map an unknown destination host to the manual host branch."""
    lookup = _lookup(
        _service(5, name="src-svc", address="src-host", port=3306),
    )
    task = _legacy_archives_task(
        name="arch-4",
        purge_item={
            "ALIAS": "arch-4",
            "SOURCE_DB": "src_db",
            "SOURCE_TABLE": "src_table",
            "DEST_HOST": "dst-host",
            "DEST_PORT": 3307,
            "DEST_TABLE": "dst_table",
            "SWAP_DROP": 0,
            "WHERE": "id < 100",
        },
    )

    body = reconstruct_archives_form(task, _ctx(lookup))

    assert body is not None
    assert body["host"] == {
        "mode": "manual",
        "dest_host": "dst-host",
        "dest_port": 3307,
    }
    ArchivesCreate.model_validate(body)


def test_reconstruct_archives_form_resolves_destination_service():
    """Resolve a destination host to the inventory service host branch."""
    lookup = _lookup(
        _service(6, name="src-svc", address="src-host", port=3306),
        _service(9, name="dst-svc", address="dst-host", port=3307),
    )
    task = _legacy_archives_task(
        name="arch-4b",
        purge_item={
            "ALIAS": "arch-4b",
            "SOURCE_DB": "src_db",
            "SOURCE_TABLE": "src_table",
            "DEST_HOST": "dst-host",
            "DEST_PORT": 3307,
            "DEST_TABLE": "dst_table",
            "SWAP_DROP": 0,
            "WHERE": "id < 100",
        },
    )

    body = reconstruct_archives_form(task, _ctx(lookup))

    assert body is not None
    assert body["host"] == {"mode": "service", "dest_service": 9}
    ArchivesCreate.model_validate(body)


def test_reconstruct_archives_form_returns_none_when_service_unresolved():
    """Skip tasks whose source host cannot be matched in inventory."""
    lookup = _lookup(
        _service(1, name="src-svc", address="src-host", port=3306),
    )
    task = _legacy_archives_task(
        source_host="unknown.internal",
        service_name="missing",
        purge_item={
            "ALIAS": "arch-x",
            "SOURCE_DB": "src_db",
            "SOURCE_TABLE": "src_table",
            "DEST_TABLE": "dst_table",
            "SWAP_DROP": 0,
            "WHERE": "id < 1",
        },
    )

    assert reconstruct_archives_form(task, _ctx(lookup)) is None


def test_reconstruct_archives_form_returns_none_without_purge_list():
    """Skip tasks whose config omits ``PURGE_LIST``."""
    lookup = _lookup(
        _service(1, name="src-svc", address="src-host", port=3306),
    )
    task = _legacy_archives_task(
        purge_item={
            "ALIAS": "ignored",
            "SOURCE_DB": "src_db",
            "SOURCE_TABLE": "src_table",
            "DEST_TABLE": "dst_table",
            "SWAP_DROP": 0,
            "WHERE": "id < 1",
        },
    )
    task.data["meta"]["config"] = yaml.dump({"ALL": {"SOURCE_HOST": "src-host"}})

    assert reconstruct_archives_form(task, _ctx(lookup)) is None


def test_reconstruct_archives_form_returns_none_when_not_run_python():
    """Skip tasks that are not ``run-python`` archiver rows."""
    lookup = _lookup(
        _service(1, name="src-svc", address="src-host", port=3306),
    )
    task = _legacy_archives_task(
        purge_item={
            "ALIAS": "arch-x",
            "SOURCE_DB": "src_db",
            "SOURCE_TABLE": "src_table",
            "DEST_TABLE": "dst_table",
            "SWAP_DROP": 0,
            "WHERE": "id < 1",
        },
    )
    task.data["task"] = "run-command"

    assert reconstruct_archives_form(task, _ctx(lookup)) is None


def test_reconstruct_archives_form_returns_none_when_missing_target():
    """Skip tasks whose executor host is absent from ``meta['target']``."""
    lookup = _lookup(
        _service(1, name="src-svc", address="src-host", port=3306),
    )
    task = _legacy_archives_task(
        target="",
        purge_item={
            "ALIAS": "arch-x",
            "SOURCE_DB": "src_db",
            "SOURCE_TABLE": "src_table",
            "DEST_TABLE": "dst_table",
            "SWAP_DROP": 0,
            "WHERE": "id < 1",
        },
    )

    assert reconstruct_archives_form(task, _ctx(lookup)) is None


def test_backfill_single_task_skips_archives_swap_drop_invalid():
    """Reject legacy SWAP_DROP tasks at create-model validation."""
    lookup = _lookup(
        _service(8, name="src-svc", address="src-host", port=3306),
    )
    task = _legacy_archives_task(
        purge_item={
            "ALIAS": "arch-swap",
            "SOURCE_DB": "src_db",
            "SOURCE_TABLE": "src_table",
            "DEST_TABLE": "dst_table",
            "SWAP_DROP": SwapDropEnum.SWAP_DROP.value,
            "WHERE": "id < 50",
        },
    )
    entry = FORM_BACKFILL_ENTRIES[0]
    ctx = FormBackfillContext(
        log=__import__("logging").getLogger("test"),
        service_lookup=lookup,
    )

    outcome = _backfill_single_task(task, entry, ctx)

    assert outcome.label == "skipped_invalid"
    assert outcome.stamped_data is None


def test_backfill_single_task_stamps_archives_form():
    """Run the orchestrator pipeline for a reconstructable archives task."""
    expected_service_id = 8
    lookup = _lookup(
        _service(
            expected_service_id,
            name="src-svc",
            address="src-host",
            port=3306,
        ),
    )
    task = _legacy_archives_task(
        name="arch-stamp",
        alert_on_fail=True,
        purge_item={
            "ALIAS": "arch-stamp",
            "SOURCE_DB": "src_db",
            "SOURCE_TABLE": "src_table",
            "DEST_TABLE": "dst_table",
            "SWAP_DROP": 0,
            "WHERE": "id < 50",
        },
    )
    entry = FORM_BACKFILL_ENTRIES[0]
    ctx = FormBackfillContext(
        log=__import__("logging").getLogger("test"),
        service_lookup=lookup,
    )

    outcome = _backfill_single_task(task, entry, ctx)

    assert outcome.label == "stamped"
    assert outcome.stamped_data is not None
    stamped_form = outcome.stamped_data[RESERVED_FORM_KEY]
    assert stamped_form["task_name"] == "arch-stamp"
    assert stamped_form["service_id"] == expected_service_id
    assert stamped_form["alert_on_fail"] is True
