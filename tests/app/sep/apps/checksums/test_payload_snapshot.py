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

"""Freeze the byte-identity guardrail for the checksums Nomad payload.

Capture the full ``TaskWrite`` envelope produced by the model-first spec path
(``build_checksums_spec`` + ``assemble_envelope``) across a matrix of
representative inputs, and compare each against a committed golden, captured
from a known-good baseline so any drift in the generated ``meta.args`` (or the
surrounding envelope) fails loudly.
"""

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.checksums.models import ChecksumsForm
from app.sep.apps.checksums.spec import build_checksums_spec
from app.sep.apps.framework.spec import assemble_envelope, ResolvedEntities
from app.sep.inventory import CreatedService
from tests.app.factories import CreatedNodeFactory, CreatedServiceFactory
from tests.app.sep.snapshot_utils import assert_or_update, canonical_json, SNAPSHOTS_DIR

PAYLOAD_DIR = SNAPSHOTS_DIR / "payload"

_DEFAULT_SERVICE = {"address": "db.internal", "port": 3306, "name": "svc-checksums"}

# Each case names a slug, the inventory service shape (DSN host/port source), the
# checksums field values, and — for the legacy form path only — the raw
# ``extra_args`` the Jinja route threads through (parsed into remaining args).
# ``form_only`` cases exercise a leg the model-first JSON path cannot reach
# (extra_args), so they are skipped by the spec-path golden.
_CASES = [
    {
        "slug": "defaults_minimal",
        "service": _DEFAULT_SERVICE,
        "form": {"recursion_method": "processlist"},
        "alert_on_fail": False,
    },
    {
        "slug": "all_options_and_flags",
        "service": _DEFAULT_SERVICE,
        "form": {
            "databases": "db1,db2",
            "tables": "db1.t1,db1.t2",
            "pause_file": "/var/run/checksums.pause",
            "binary_index": True,
            "explain_arg": True,
            "fail_on_stopped_replication": True,
            "truncate_replicate_table": True,
            "progress": "time,10",
            "set_vars": "sql_mode=STRICT_ALL_TABLES",
            "max_load": "Threads_running=50",
            "chunk_time": "0.5",
            "max_lag": "150",
            "recursion_method": "processlist",
        },
        "alert_on_fail": True,
    },
    {
        "slug": "dsn_recursion_default_table",
        "service": _DEFAULT_SERVICE,
        "form": {"recursion_method": "dsn", "dsn_table": ""},
        "alert_on_fail": False,
    },
    {
        "slug": "dsn_recursion_custom_table",
        "service": _DEFAULT_SERVICE,
        "form": {"recursion_method": "dsn", "dsn_table": "D=mydb,t=custom_dsns"},
        "alert_on_fail": False,
    },
    {
        "slug": "recursion_none",
        "service": _DEFAULT_SERVICE,
        "form": {"recursion_method": "none"},
        "alert_on_fail": False,
    },
    {
        "slug": "port_none_localhost_dsn_elision",
        "service": {"address": "localhost", "port": None, "name": "svc-local"},
        "form": {"recursion_method": "dsn", "dsn_table": ""},
        "alert_on_fail": False,
    },
    {
        "slug": "value_with_space_quoting",
        "service": _DEFAULT_SERVICE,
        "form": {
            "recursion_method": "processlist",
            "databases": "reporting db",
            "set_vars": "sql_mode='ONLY FULL'",
        },
        "alert_on_fail": False,
    },
    {
        "slug": "legacy_extra_remaining_args",
        "service": _DEFAULT_SERVICE,
        "form": {"recursion_method": "processlist", "databases": "main"},
        "alert_on_fail": True,
        "extra_args": "--no-check-binlog-format",
        "form_only": True,
    },
]

_TASK_NAME = "checksums-golden"
_HOSTNAME = "executor-host"


def _service(case: dict) -> CreatedService:
    """Return the deterministic inventory service the case's DSN derives from."""
    spec = case["service"]
    node = CreatedNodeFactory.build(address=spec["address"])
    return CreatedServiceFactory.build(
        node=node,
        type=ServiceTypeEnum.MYSQL,
        name=spec["name"],
        port=spec["port"],
    )


def _spec_envelope(case: dict) -> dict:
    """Return the model-first ``TaskWrite`` dump for ``case``."""
    service = _service(case)
    resolved = ResolvedEntities(
        service=service,
        entities={"service_id": service},
        executor_host=_HOSTNAME,
    )
    form = ChecksumsForm(
        task_name=_TASK_NAME,
        hostname=_HOSTNAME,
        service_id=service.id,
        **case["form"],
    )
    databases_arg = ",".join(str(value) for value in form.databases)
    tables_arg = ",".join(str(value) for value in form.tables)
    task = assemble_envelope(
        build_checksums_spec(
            form,
            resolved,
            databases_arg=databases_arg,
            tables_arg=tables_arg,
        ),
        resolved,
        name=_TASK_NAME,
        owner="CHECKSUMS",
        alert_on_fail=case["alert_on_fail"],
    )
    return task.model_dump()


def test_spec_path_payload_matrix_matches_golden():
    """Assert the model-first spec path reproduces the frozen envelope matrix."""
    payloads = {
        case["slug"]: _spec_envelope(case)
        for case in _CASES
        if not case.get("form_only")
    }
    assert_or_update(
        PAYLOAD_DIR / "checksums__spec_path.json", canonical_json(payloads)
    )
