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

"""Tests for the checksums legacy form reconstructor."""

from types import SimpleNamespace

import pytest

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.checksums.form_backfill import (
    _split_checksums_dsn_recursion,
    FORM_BACKFILL_ENTRIES,
    reconstruct_checksums_form,
)
from app.sep.apps.checksums.models import ChecksumsForm
from app.sep.apps.framework.form_backfill import (
    _backfill_single_task,
    FormBackfillContext,
)
from app.sep.apps.framework.form_backfill_inventory import ServiceIdLookup
from app.sep.apps.framework.spec import RESERVED_FORM_KEY
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


def _legacy_checksums_task(
    *,
    name: str = "chk-legacy",
    args: str,
    target: str = "executor-1",
    service_host: str = "10.0.0.5",
    service_port: int = 3306,
    service_name: str = "mysql-prod",
    alert_on_fail: bool = False,
) -> Task:
    """Build a legacy checksums task row without ``data['_form']``."""
    return Task(
        name=name,
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-table-checksum",
                "args": args,
                "target": target,
                "_service_host": service_host,
                "_service_port": service_port,
                "_service_name": service_name,
            },
        },
        backend=TaskBackendEnum.PROXY,
        owner="CHECKSUMS",
        alert_on_fail=alert_on_fail,
    )


@pytest.mark.parametrize(
    ("stored", "expected_method", "expected_dsn_table"),
    [
        ("processlist", "processlist", ""),
        ("hosts", "hosts", ""),
        ("dsn", "dsn", ""),
        (
            "dsn=h=db.internal,P=3306,D=mydb,t=custom_dsns",
            "dsn",
            "D=mydb,t=custom_dsns",
        ),
        (
            "dsn=,D=percona,t=dsns",
            "dsn",
            "D=percona,t=dsns",
        ),
        (
            "dsn=h=db.internal,P=3306,D=percona,t=dsns",
            "dsn",
            "D=percona,t=dsns",
        ),
    ],
)
def test_split_checksums_dsn_recursion(stored, expected_method, expected_dsn_table):
    """Split persisted recursion-method strings into form fields."""
    assert _split_checksums_dsn_recursion(stored) == (
        expected_method,
        expected_dsn_table,
    )


def test_reconstruct_checksums_form_happy_path():
    """Rebuild a create body from legacy meta and CLI args."""
    lookup = _lookup(
        _service(42, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_checksums_task(
        args=(
            "h=10.0.0.5,P=3306, --recursion-method=processlist "
            "--databases=db1,db2 --binary-index"
        ),
        alert_on_fail=True,
    )

    body = reconstruct_checksums_form(task, _ctx(lookup))

    assert body == {
        "task_name": "chk-legacy",
        "hostname": "executor-1",
        "service_id": 42,
        "recursion_method": "processlist",
        "dsn_table": "",
        "databases": ["db1", "db2"],
        "tables": [],
        "pause_file": "",
        "binary_index": True,
        "explain_arg": False,
        "fail_on_stopped_replication": False,
        "truncate_replicate_table": False,
        "progress": "",
        "set_vars": "",
        "max_load": "",
        "chunk_time": "",
        "max_lag": "",
        "defaults_file": "",
        "alert_on_fail": True,
    }
    ChecksumsForm.model_validate(body)


def test_reconstruct_checksums_form_defaults_file():
    """Rebuild ``defaults_file`` from legacy ``--defaults-file`` args."""
    lookup = _lookup(
        _service(42, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_checksums_task(
        args=(
            "h=10.0.0.5,P=3306, --recursion-method=processlist "
            "--defaults-file=/etc/checksum.cnf"
        ),
    )

    body = reconstruct_checksums_form(task, _ctx(lookup))

    assert body is not None
    assert body["defaults_file"] == "/etc/checksum.cnf"
    ChecksumsForm.model_validate(body)


def test_reconstruct_checksums_form_returns_none_when_service_unresolved():
    """Skip tasks whose host/port cannot be matched in inventory."""
    lookup = _lookup(
        _service(42, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_checksums_task(
        args="h=10.0.0.9,P=3306, --recursion-method=processlist",
        service_host="10.0.0.9",
        service_name="unknown-service",
    )

    assert reconstruct_checksums_form(task, _ctx(lookup)) is None


def test_reconstruct_checksums_form_returns_none_for_non_checksums_command():
    """Skip tasks whose meta command is not ``pt-table-checksum``."""
    lookup = _lookup(
        _service(42, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_checksums_task(args="--recursion-method=processlist")
    task.data["meta"]["command"] = "other-tool"

    assert reconstruct_checksums_form(task, _ctx(lookup)) is None


def test_reconstruct_checksums_form_returns_none_when_missing_target():
    """Skip tasks whose executor host is absent from ``meta['target']``."""
    lookup = _lookup(
        _service(42, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_checksums_task(
        args="h=10.0.0.5,P=3306, --recursion-method=processlist"
    )
    task.data["meta"]["target"] = ""

    assert reconstruct_checksums_form(task, _ctx(lookup)) is None


def test_reconstruct_checksums_form_dsn_recursion_happy_path():
    """Rebuild a body when legacy args expanded ``dsn`` recursion."""
    lookup = _lookup(
        _service(42, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_checksums_task(
        args=(
            "h=10.0.0.5,P=3306, --recursion-method="
            "dsn=h=10.0.0.5,P=3306,D=percona,t=custom_dsns"
        ),
    )

    body = reconstruct_checksums_form(task, _ctx(lookup))

    assert body is not None
    assert body["recursion_method"] == "dsn"
    assert body["dsn_table"] == "D=percona,t=custom_dsns"
    ChecksumsForm.model_validate(body)


def test_backfill_single_task_stamps_checksums_form():
    """Run the orchestrator pipeline for a reconstructable checksums task."""
    expected_service_id = 7
    lookup = _lookup(
        _service(expected_service_id, name="mysql-prod", address="10.0.0.5", port=3306),
    )
    task = _legacy_checksums_task(
        name="chk-stamp",
        args="h=10.0.0.5,P=3306, --recursion-method=hosts --tables=db.t1",
    )
    entry = FORM_BACKFILL_ENTRIES[0]
    ctx = FormBackfillContext(
        log=__import__("logging").getLogger("test"),
        service_lookup=lookup,
    )

    outcome = _backfill_single_task(task, entry, ctx)

    assert outcome.label == "stamped"
    assert outcome.stamped_data is not None
    assert RESERVED_FORM_KEY in outcome.stamped_data
    stamped_form = outcome.stamped_data[RESERVED_FORM_KEY]
    assert stamped_form["task_name"] == "chk-stamp"
    assert stamped_form["service_id"] == expected_service_id
    assert stamped_form["recursion_method"] == "hosts"
    assert stamped_form["tables"] == ["db.t1"]
