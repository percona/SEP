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

Capture the full ``TaskWrite`` envelope produced by both the model-first spec
path (``build_checksums_spec`` + ``assemble_envelope``) and the legacy Jinja form
path (``assemble_checksum_payload``) across a matrix of representative inputs,
and compare each against a committed golden. A declarative rewrite that shifts
both code paths together would slip past the form-vs-spec parity test in
``test_deps.py``; this golden is captured from a known-good baseline so any drift
in the generated ``meta.args`` (or the surrounding envelope) fails loudly.
"""

from unittest.mock import AsyncMock

import pytest

from app.core.requests.remote_api import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.checksums.deps import build_checksums_task_payload
from app.sep.apps.checksums.models import ChecksumsCreate, ChecksumsForm
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
    task = assemble_envelope(
        build_checksums_spec(form, resolved),
        resolved,
        name=_TASK_NAME,
        owner="CHECKSUMS",
        alert_on_fail=case["alert_on_fail"],
    )
    return task.model_dump()


async def _form_envelope(case: dict) -> dict:
    """Return the legacy Jinja-path ``TaskWrite`` dump for ``case``.

    Drive the public ``build_checksums_task_payload`` entry point with a boundary
    inventory mock that serves the case's deterministic service.
    """
    service = _service(case)
    inventory = AsyncMock(spec=RemoteAPI)
    inventory.get = AsyncMock(return_value=service.model_dump())
    form = ChecksumsCreate(
        task_name=_TASK_NAME,
        hostname=_HOSTNAME,
        service_id=service.id,
        recursion_method=case["form"].get("recursion_method", "processlist"),
        dsn_table=case["form"].get("dsn_table", ""),
        databases=case["form"].get("databases", ""),
        tables=case["form"].get("tables", ""),
        pause_file=case["form"].get("pause_file", ""),
        binary_index=case["form"].get("binary_index", False),
        explain_arg=case["form"].get("explain_arg", False),
        fail_on_stopped_replication=case["form"].get(
            "fail_on_stopped_replication", False
        ),
        truncate_replicate_table=case["form"].get("truncate_replicate_table", False),
        progress=case["form"].get("progress", ""),
        set_vars=case["form"].get("set_vars", ""),
        max_load=case["form"].get("max_load", ""),
        chunk_time=case["form"].get("chunk_time", ""),
        max_lag=case["form"].get("max_lag", ""),
        alert_on_fail=case["alert_on_fail"],
        extra_args=case.get("extra_args", ""),
    )
    task = await build_checksums_task_payload(form, inventory)
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


@pytest.mark.asyncio
async def test_form_path_payload_matrix_matches_golden():
    """Assert the legacy Jinja form path reproduces the frozen envelope matrix."""
    payloads = {case["slug"]: await _form_envelope(case) for case in _CASES}
    assert_or_update(
        PAYLOAD_DIR / "checksums__form_path.json", canonical_json(payloads)
    )
