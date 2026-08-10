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

"""Freeze the byte-identity guardrail for the alters pt-osc parent Nomad payload.

Capture the full parent-execute ``TaskWrite`` envelope produced by both the
inventory-resolving ``build_alters_task`` entry point and the pure
``build_alters_spec`` + ``assemble_envelope`` spec path across a matrix of
representative inputs, and compare each against a single committed golden. The
golden is captured from origin/main via ``build_alters_task`` *before* the
declarative-spec refactor, so any drift in the generated ``meta.args`` (or the
surrounding envelope) after the refactor fails loudly rather than silently
ratifying the rewrite's own output.
"""

from unittest.mock import AsyncMock

import pytest

from app.core.requests.remote_api import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.alters.deps import (
    build_alters_task,
)
from app.sep.apps.alters.models import AltersCreate
from app.sep.apps.alters.spec import build_alters_spec
from app.sep.apps.framework.spec import assemble_envelope, ResolvedEntities
from app.sep.inventory import CreatedService
from tests.app.factories import CreatedNodeFactory, CreatedServiceFactory
from tests.app.sep.snapshot_utils import assert_or_update, canonical_json, SNAPSHOTS_DIR

PAYLOAD_DIR = SNAPSHOTS_DIR / "payload"

_REMOTE_SERVICE = {"address": "db.internal", "port": 3306, "name": "svc-alters"}
_LOCAL_SERVICE = {"address": "localhost", "port": None, "name": "svc-local"}

_TASK_NAME = "alters-golden"
_HOSTNAME = "executor-host"

# Each case names a slug, the inventory service shape (DSN host/port source), and
# the alters field values folded onto the required base. The db_schema / db_table
# targets are free-typed names so ``resolve_refs`` fetches only the service (one
# inventory call), and the DSN derives from ``str(form.db_schema|db_table)``.
_CASES = [
    {
        "slug": "required_minimal",
        "service": _REMOTE_SERVICE,
        "form": {},
    },
    {
        "slug": "all_value_args",
        "service": _REMOTE_SERVICE,
        "form": {
            "pause_file": "/var/run/osc.pause",
            "new_table_name": "_users_new",
            "tries": "create_triggers:10000:1,drop_triggers:10000:1",
            "set_vars": "lock_wait_timeout=5",
            "critical_load": "Threads_running=99999,Connections=200",
            "max_load": "Threads_running=30,Threads_connected=120",
            "chunk_time": "0.5",
            "max_lag": "150",
            "max_flow_ctl": "25",
        },
    },
    {
        "slug": "all_flags",
        "service": _REMOTE_SERVICE,
        "form": {
            "print_arg": True,
            "no_swap_tables": True,
            "no_drop_old_table": True,
            "no_drop_new_table": True,
            "no_drop_triggers": True,
        },
    },
    {
        "slug": "local_portless_dsn_elision",
        "service": _LOCAL_SERVICE,
        "form": {},
    },
    {
        "slug": "dsn_recursion_default_table",
        "service": _REMOTE_SERVICE,
        "form": {"recursion_method": "dsn", "dsn_table": ""},
    },
    {
        "slug": "dsn_recursion_custom_table",
        "service": _REMOTE_SERVICE,
        "form": {"recursion_method": "dsn", "dsn_table": "D=mydb,t=custom_dsns"},
    },
    {
        "slug": "value_with_space_quoting",
        "service": _REMOTE_SERVICE,
        "form": {"set_vars": "sql_mode='ONLY FULL'"},
    },
    {
        "slug": "extra_args_tokens",
        "service": _REMOTE_SERVICE,
        "form": {"extra_args": "--sleep 0.5 --chunk-size 1000"},
    },
    {
        "slug": "defaults_file_custom",
        "service": _REMOTE_SERVICE,
        "form": {"pre_checks_mysql_config_file": "/etc/mysql/exec.cnf"},
    },
    {
        "slug": "progress_after_flags",
        "service": _REMOTE_SERVICE,
        "form": {"progress": "time,10", "no_swap_tables": True},
    },
]


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


def _form(case: dict, service: CreatedService) -> AltersCreate:
    """Build the validated ``AltersCreate`` for ``case`` targeting ``service``."""
    return AltersCreate(
        task_name=_TASK_NAME,
        hostname=_HOSTNAME,
        service_id=service.id,
        db_schema="app",
        db_table="users",
        alter="ADD COLUMN new_col INT",
        recursion_method=case["form"].get("recursion_method", "processlist"),
        **{
            key: value
            for key, value in case["form"].items()
            if key != "recursion_method"
        },
    )


def _spec_envelope(case: dict) -> dict:
    """Return the pure ``build_alters_spec`` + ``assemble_envelope`` dump for ``case``.

    Drive the spec path directly with a ``ResolvedEntities`` whose free-typed
    schema and table resolve to no entity, so the DSN derives from the raw form
    values — the same shape the task path produces.
    """
    service = _service(case)
    form = _form(case, service)
    resolved = ResolvedEntities(
        service=service,
        entities={"db_schema": None, "db_table": None},
        executor_host=_HOSTNAME,
    )
    task = assemble_envelope(
        build_alters_spec(form, resolved),
        resolved,
        name=_TASK_NAME,
        owner="ALTERS",
        alert_on_fail=form.alert_on_fail,
    )
    return task.model_dump()


async def _task_envelope(case: dict) -> dict:
    """Return the ``build_alters_task`` ``TaskWrite`` dump for ``case``.

    Drive the public inventory-resolving entry point with a boundary inventory
    mock that serves the case's deterministic service; the free-typed schema and
    table resolve to no entity, so only the service is fetched.
    """
    service = _service(case)
    inventory = AsyncMock(spec=RemoteAPI)
    inventory.get = AsyncMock(return_value=service.model_dump())
    task = await build_alters_task(_form(case, service), inventory)
    return task.model_dump()


def test_spec_path_payload_matrix_matches_golden():
    """Assert the pure spec path reproduces the frozen envelope matrix."""
    payloads = {case["slug"]: _spec_envelope(case) for case in _CASES}
    assert_or_update(PAYLOAD_DIR / "alters__payload.json", canonical_json(payloads))


@pytest.mark.asyncio
async def test_task_path_payload_matrix_matches_golden():
    """Assert the inventory-resolving task path reproduces the frozen envelope matrix."""
    payloads = {case["slug"]: await _task_envelope(case) for case in _CASES}
    assert_or_update(PAYLOAD_DIR / "alters__payload.json", canonical_json(payloads))
