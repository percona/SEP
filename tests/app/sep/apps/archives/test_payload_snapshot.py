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

"""Pin the archives task payload and assert the JSON and Jinja paths agree.

The spec-path matrix builds the ``run-python`` envelope directly through
:func:`build_archives_spec` + ``assemble_envelope`` (the model-first JSON create
path) over the source / destination / host permutations, and the form-path test
drives the same case through the legacy flat-form dependency
:func:`build_archives_task_payload` — so a form-created task's payload stays
byte-identical to a JSON-created one.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.requests.remote_api import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.archives.deps import (
    ArchivesLegacyForm,
    build_archives_task_payload,
)
from app.sep.apps.archives.models import ArchivesCreate
from app.sep.apps.archives.spec import build_archives_spec
from app.sep.apps.framework.spec import assemble_envelope, ResolvedEntities
from app.sep.inventory import CreatedService
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
)
from tests.app.sep.snapshot_utils import assert_or_update, canonical_json, SNAPSHOTS_DIR

GOLDEN = SNAPSHOTS_DIR / "payload" / "archives__payload.json"
_PAYLOAD_ANCHOR = "app/sep/apps/archives/"
_HOSTNAME = "executor-host"

_SOURCE_SERVICE = CreatedServiceFactory.build(
    id=1,
    node=CreatedNodeFactory.build(address="src-host", name="src-node"),
    type=ServiceTypeEnum.MYSQL,
    name="src-svc",
    port=3306,
)
_DEST_SERVICE = CreatedServiceFactory.build(
    id=2,
    node=CreatedNodeFactory.build(address="dst-host", name="dst-node"),
    type=ServiceTypeEnum.MYSQL,
    name="dst-svc",
    port=3307,
)
_SOURCE_SCHEMA = CreatedSchemaFactory.build(id=1, name="src_db")
_SOURCE_TABLE = CreatedTableFactory.build(id=1, name="src_table")
_DEST_TABLE = CreatedTableFactory.build(id=2, name="dst_table")
_DEST_SCHEMA = CreatedSchemaFactory.build(id=2, name="dst_db")


def _normalize(envelope: dict[str, Any]) -> dict[str, Any]:
    """Rewrite the absolute ``file://`` payload path to a package-relative anchor."""
    payload = envelope["data"]["payload"]
    suffix = payload.split(_PAYLOAD_ANCHOR)[-1]
    envelope["data"]["payload"] = f"file://{_PAYLOAD_ANCHOR}{suffix}"
    return envelope


def _envelope(form: ArchivesCreate, resolved: ResolvedEntities) -> dict[str, Any]:
    """Build the normalized run-python envelope for the spec (JSON) path."""
    task = assemble_envelope(
        build_archives_spec(form, resolved),
        resolved,
        name=form.task_name,
        owner="ARCHIVER",
        alert_on_fail=form.alert_on_fail,
        alert_detail_builder="app.sep.apps.archives.alerts:build_owner_alert_details",
    )
    return _normalize(task.model_dump())


# Each case: (slug, ArchivesCreate body kwargs, resolved entities by dotted key).
_CASES: list[tuple[str, dict[str, Any], dict[str, CreatedService | None]]] = [
    (
        "table_to_table_same_host",
        {
            "task_name": "arch-1",
            "hostname": _HOSTNAME,
            "service_id": 1,
            "source": {"mode": "table", "source_db": 1, "source_table": 1},
            "destination": {"mode": "table", "dest_table": 2},
            "where": "id < 100",
        },
        {
            "source.source_db": _SOURCE_SCHEMA,
            "source.source_table": _SOURCE_TABLE,
            "destination.dest_table": _DEST_TABLE,
            "destination.dest_db": None,
        },
    ),
    (
        "table_to_file",
        {
            "task_name": "arch-2",
            "hostname": _HOSTNAME,
            "service_id": 1,
            "source": {"mode": "table", "source_db": 1, "source_table": 1},
            "destination": {"mode": "file", "dest_file": "/data/out.csv"},
            "where": "id < 100",
            "disable_bulk_insert": True,
        },
        {"source.source_db": _SOURCE_SCHEMA, "source.source_table": _SOURCE_TABLE},
    ),
    (
        "query_to_table",
        {
            "task_name": "arch-3",
            "hostname": _HOSTNAME,
            "service_id": 1,
            "source": {"mode": "query", "source_query": "SELECT * FROM t"},
            "destination": {"mode": "table", "dest_table": 2, "dest_db": 2},
            "where": "id < 100",
        },
        {"destination.dest_table": _DEST_TABLE, "destination.dest_db": _DEST_SCHEMA},
    ),
    (
        "dest_service_host",
        {
            "task_name": "arch-4",
            "hostname": _HOSTNAME,
            "service_id": 1,
            "source": {"mode": "table", "source_db": 1, "source_table": 1},
            "destination": {"mode": "table", "dest_table": 2},
            "host": {"mode": "service", "dest_service": 2},
            "where": "id < 100",
        },
        {
            "source.source_db": _SOURCE_SCHEMA,
            "source.source_table": _SOURCE_TABLE,
            "destination.dest_table": _DEST_TABLE,
            "host.dest_service": _DEST_SERVICE,
        },
    ),
    (
        "manual_host_free_solo_names",
        {
            "task_name": "arch-5",
            "hostname": _HOSTNAME,
            "service_id": 1,
            "source": {
                "mode": "table",
                "source_db": "typed_db",
                "source_table": "typed_tbl",
            },
            "destination": {"mode": "table", "dest_table": "typed_dest"},
            "host": {"mode": "manual", "dest_host": "remote-host", "dest_port": 3309},
            "where": "id < 100",
            "use_index": "idx_a",
            "limit": 500,
            "sleep": 1,
        },
        {
            "source.source_db": None,
            "source.source_table": None,
            "destination.dest_table": None,
        },
    ),
    (
        "delete_data_no_dest",
        {
            "task_name": "arch-6",
            "hostname": _HOSTNAME,
            "service_id": 1,
            "source": {"mode": "table", "source_db": 1, "source_table": 1},
            "delete_data": True,
            "where": "id < 100",
        },
        {"source.source_db": _SOURCE_SCHEMA, "source.source_table": _SOURCE_TABLE},
    ),
]


def test_spec_path_payload_matrix_matches_golden() -> None:
    """Pin the model-first JSON create payload across the source/dest/host matrix."""
    payloads = {}
    for slug, body, entities in _CASES:
        form = ArchivesCreate.model_validate(body)
        resolved = ResolvedEntities(
            service=_SOURCE_SERVICE, entities=entities, executor_host=_HOSTNAME
        )
        payloads[slug] = _envelope(form, resolved)
    assert_or_update(GOLDEN, canonical_json(payloads))


def _fake_inventory() -> AsyncMock:
    """Return an inventory mock resolving the seeded source/dest entities by path."""
    routes = {
        "/services/1": _SOURCE_SERVICE.model_dump(mode="json"),
        "/services/2": _DEST_SERVICE.model_dump(mode="json"),
        "/schemas/1": _SOURCE_SCHEMA.model_dump(mode="json"),
        "/schemas/2": _DEST_SCHEMA.model_dump(mode="json"),
        "/tables/1": _SOURCE_TABLE.model_dump(mode="json"),
        "/tables/2": _DEST_TABLE.model_dump(mode="json"),
    }
    api = AsyncMock(spec=RemoteAPI)

    async def _get(path: str, params: dict | None = None) -> dict:
        return routes[path]

    api.get.side_effect = _get
    return api


@pytest.mark.asyncio
async def test_form_path_matches_spec_path() -> None:
    """Assert the legacy flat-form path yields the same payload as the JSON path."""
    spec_form = ArchivesCreate.model_validate(_CASES[0][1])
    spec_resolved = ResolvedEntities(
        service=_SOURCE_SERVICE, entities=_CASES[0][2], executor_host=_HOSTNAME
    )
    spec_payload = _envelope(spec_form, spec_resolved)

    flat = ArchivesLegacyForm.model_validate(
        {
            "alias": "arch-1",
            "hostname": _HOSTNAME,
            "service_id": 1,
            "source_db_id": 1,
            "source_table_id": 1,
            "dest_table_id": 2,
            "swap_drop": 0,
            "where": "id < 100",
        }
    )
    form_task = await build_archives_task_payload(flat, _fake_inventory())
    form_payload = _normalize(form_task.model_dump())

    assert form_payload == spec_payload
