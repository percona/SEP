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

"""Freeze the byte-identity guardrail for the backup_pg run-python payload.

Capture the full ``TaskWrite`` envelope produced by both the model-first spec
path (``build_backup_pg_spec`` + ``assemble_envelope``) and the legacy Jinja form
path (``deps.build_backup_task_payload``) across a matrix of representative
inputs, and compare each against a committed golden. Both paths feed the same
spec builder, so the golden is shared; any drift in the generated ``meta.config``
YAML (or the surrounding envelope) fails loudly.
"""

from unittest.mock import AsyncMock

import pytest

from app.core.requests.remote_api import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_pg.deps import build_backup_task_payload
from app.sep.apps.backup_pg.models import BackupPgForm
from app.sep.apps.backup_pg.spec import build_backup_pg_spec
from app.sep.apps.framework.spec import assemble_envelope, ResolvedEntities
from app.sep.inventory import CreatedService
from tests.app.factories import CreatedNodeFactory, CreatedServiceFactory
from tests.app.sep.snapshot_utils import assert_or_update, canonical_json, SNAPSHOTS_DIR

PAYLOAD_DIR = SNAPSHOTS_DIR / "payload"
GOLDEN = PAYLOAD_DIR / "backup_pg__payload.json"
_PAYLOAD_ANCHOR = "app/sep/apps/backup_pg/"


def _normalize(envelope: dict) -> dict:
    """Rewrite the absolute ``file://`` payload to the package-relative anchor.

    ``Path(__file__).parent`` resolves to an absolute path that varies per
    checkout; anchoring it keeps the committed golden stable across machines.
    """
    payload = envelope["data"]["payload"]
    suffix = payload.split(_PAYLOAD_ANCHOR)[-1]
    envelope["data"]["payload"] = f"file://{_PAYLOAD_ANCHOR}{suffix}"
    return envelope


_DEFAULT_SERVICE = {"address": "db.internal", "port": 5432, "name": "svc-backup-pg"}

# Each case names a slug, the inventory service shape (config host/port source),
# the backup_pg form field values, and the create-time alert_on_fail flag.
_CASES = [
    {
        "slug": "defaults_minimal",
        "service": _DEFAULT_SERVICE,
        "form": {"stanza": "sep-test", "backup_dir": "/var/lib/pgbackrest"},
        "alert_on_fail": False,
    },
    {
        "slug": "all_pgbackrest_options",
        "service": _DEFAULT_SERVICE,
        "form": {
            "stanza": "prod-main",
            "backup_dir": "/srv/backups",
            "pgbackrest_backup_type": "diff",
            "pgbackrest_bin": "/usr/local/bin/pgbackrest",
            "pgbackrest_config_file": "/etc/pgbackrest/pgbackrest.conf",
            "pgbackrest_datadir": "/var/lib/postgresql/16/main",
            "pgbackrest_retention_full": 4,
            "pgbackrest_retention_archive": 8,
            "pgbackrest_incremental_cycle": "daily",
            "logging_dir": "/var/log/pgbackrest",
        },
        "alert_on_fail": True,
    },
    {
        "slug": "port_none_omits_server_port",
        "service": {"address": "localhost", "port": None, "name": "svc-local"},
        "form": {"stanza": "local-stanza", "backup_dir": "/var/lib/pgbackrest"},
        "alert_on_fail": False,
    },
]

_TASK_NAME = "backup-pg-golden"
_HOSTNAME = "executor-host"


def _service(case: dict) -> CreatedService:
    """Return the deterministic inventory service the case's config derives from."""
    spec = case["service"]
    node = CreatedNodeFactory.build(address=spec["address"])
    return CreatedServiceFactory.build(
        node=node,
        type=ServiceTypeEnum.POSTGRESQL,
        name=spec["name"],
        port=spec["port"],
    )


def _form(case: dict) -> BackupPgForm:
    """Return the validated create form for ``case``."""
    return BackupPgForm(
        task_name=_TASK_NAME,
        hostname=_HOSTNAME,
        service_id=_service(case).id,
        alert_on_fail=case["alert_on_fail"],
        **case["form"],
    )


def _spec_envelope(case: dict) -> dict:
    """Return the model-first ``TaskWrite`` dump for ``case``."""
    service = _service(case)
    resolved = ResolvedEntities(
        service=service,
        entities={"service_id": service},
        executor_host=_HOSTNAME,
    )
    task = assemble_envelope(
        build_backup_pg_spec(_form(case), resolved),
        resolved,
        name=_TASK_NAME,
        owner="BACKUP_PG",
        alert_on_fail=case["alert_on_fail"],
    )
    return _normalize(task.model_dump())


async def _form_envelope(case: dict) -> dict:
    """Return the legacy Jinja-path ``TaskWrite`` dump for ``case``.

    Drive ``build_backup_task_payload`` with a boundary inventory mock that serves
    the case's deterministic service.
    """
    service = _service(case)
    inventory = AsyncMock(spec=RemoteAPI)
    inventory.get = AsyncMock(return_value=service.model_dump())
    task = await build_backup_task_payload(_form(case), inventory)
    return _normalize(task.model_dump())


def test_spec_path_payload_matrix_matches_golden():
    """Assert the model-first spec path reproduces the frozen envelope matrix."""
    payloads = {case["slug"]: _spec_envelope(case) for case in _CASES}
    assert_or_update(GOLDEN, canonical_json(payloads))


@pytest.mark.asyncio
async def test_form_path_payload_matrix_matches_golden():
    """Assert the legacy Jinja form path reproduces the same frozen envelope matrix."""
    payloads = {case["slug"]: await _form_envelope(case) for case in _CASES}
    assert_or_update(GOLDEN, canonical_json(payloads))
