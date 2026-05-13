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

"""Define the JSON API router for the Inventory plugin.

Mounted at ``/api/plugins/inventory/`` via ``plugins_router`` in
``app/sep/api/router.py``. Like other plugin proxies, these routes rely on the
parent ``api_router`` for API authentication. The ``schema_endpoint`` helper
additionally attaches ``IsApiAuthenticated`` to the schema route only; list,
detail, create, update, and delete handlers do not duplicate that dependency.

Proxies CRUD for nodes, services, schemas, and tables to the inventory HTTP API
through ``InventoryAPI`` in ``app.sep.deps`` (``RemoteAPI`` toward the
inventory service). List handlers unwrap paginated ``items`` into a JSON array
for the schema-driven React client. POST and PUT bodies are parsed with the
``InventoryPluginJsonObjectBody`` in ``app.sep.plugins.inventory.deps`` (see
``inventory_plugin_json_object_body``) so non-object JSON consistently yields
HTTP 422.

Schedule and periodic sync routes are not mounted here so SEP-1058 can own the
React schedule UI; do not add schedule or inventory-sync proxy routes without
coordinating with that ticket. The inventory service remains the canonical CRUD
surface at ``/api/inventory/*``; this router is the typed entry point for the
React plugin.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.sep.deps import InventoryAPI, TaskAPI
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.inventory import payloads
from app.sep.plugins.inventory.deps import (
    inventory_plugin_query_params,
    inventory_service_create_path,
    inventory_service_detail_path,
    inventory_service_list_path,
    InventoryPluginJsonObjectBody,
    require_inventory_plugin_entity,
    unwrap_inventory_plugin_list_payload,
)
from app.sep.plugins.inventory.schema import inventory_schema
from app.sep.plugins.inventory.topology import (
    shard_hosts,
    TOPOLOGY_PAYLOAD_REQUIREMENTS,
)

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=inventory_schema)

_TOPOLOGY_PAYLOAD_PATH = Path(payloads.__file__).parent / "topology.py"
_TOPOLOGY_TASK = "run-python"
_MAX_TOPOLOGY_SHARDS = 8
class TopologyCollectBody(BaseModel):
    """Body for ``POST /topology/collect``.

    :param shards: Number of executor hosts to dispatch in parallel. Hosts
        are split round-robin across the chosen executors. Capped at
        :data:`_MAX_TOPOLOGY_SHARDS`.
    :type shards: int
    :param executor_host: Optional explicit executor; when set, overrides
        ``shards`` to a single-shard run on that host.
    :type executor_host: str | None
    :param connect_timeout: Per-host MySQL TCP connect timeout (seconds).
    :type connect_timeout: int
    :param read_timeout: Per-host MySQL read/write timeout (seconds).
    :type read_timeout: int
    """

    shards: int = Field(default=1, ge=1, le=_MAX_TOPOLOGY_SHARDS)
    executor_host: str | None = None
    connect_timeout: int = Field(default=5, ge=1, le=60)
    read_timeout: int = Field(default=10, ge=1, le=120)


class TopologyCollectResponse(BaseModel):
    """Response body for ``POST /topology/collect``.

    ``task_history_ids`` lists the dispatched ``run-python`` tasks the
    frontend then polls (``/result``) and tails (``/stream``) to
    assemble the topology graph. ``targets`` echoes the executor hosts
    the work was sharded across so the UI can surface where the
    collection ran.
    """

    task_history_ids: list[int]
    targets: list[str]
    host_count: int
    shard_count: int


class TopologyResultResponse(BaseModel):
    """Response body for ``GET /topology/result``.

    ``status`` is ``running`` while any of the underlying tasks is
    still pending, ``ok`` once every task has finished, and ``failed``
    when at least one task failed and produced no usable output.
    ``graph`` is the merged React-Flow graph; ``pending_task_ids``
    lists the still-running tasks for the UI's progress chip.
    """

    status: str
    graph: dict[str, Any] | None = None
    pending_task_ids: list[int] = Field(default_factory=list)


def _format_host_entry(service: dict[str, Any]) -> str | None:
    node = service.get("node") or {}
    address = node.get("address") or service.get("name")
    port = service.get("port") or 3306
    if not address:
        return None
    return f"{address}:{port}"


async def _collect_mysql_host_entries(inventory_api: Any) -> list[str]:
    """Return ``host:port`` entries for every MySQL service in inventory."""
    response = await inventory_api.get(
        "/services/", params={"service_type": "mysql", "limit": 0}
    )
    items = response.get("items", []) if isinstance(response, dict) else []
    seen: set[str] = set()
    hosts: list[str] = []
    for service in items:
        host_entry = _format_host_entry(service)
        if host_entry and host_entry not in seen:
            seen.add(host_entry)
            hosts.append(host_entry)
    return hosts


def _select_topology_targets(
    available_hosts: dict[str, str], requested_executor: str | None, shards: int
) -> list[str]:
    if not available_hosts:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No executor hosts available for topology collection.",
        )
    if requested_executor:
        if requested_executor not in available_hosts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Executor host {requested_executor!r} is not available.",
            )
        return [requested_executor]
    return list(available_hosts.keys())[: max(1, min(shards, _MAX_TOPOLOGY_SHARDS))]


@router.post(
    "/topology/collect",
    response_model=TopologyCollectResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def topology_collect(
    body: TopologyCollectBody,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> TopologyCollectResponse:
    """Dispatch one or more topology collector tasks. Returns the task ids.

    Hosts are pulled from the inventory MySQL service list; no inventory
    persistence side effects occur. With ``shards > 1`` the host list is
    split round-robin across the first N executor hosts so geographically
    split inventories run in parallel.
    """
    hosts = await _collect_mysql_host_entries(inventory_api)
    if not hosts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No MySQL services found in inventory.",
        )
    available_hosts = await tasks_api.get("/hosts/")
    targets = _select_topology_targets(available_hosts, body.executor_host, body.shards)
    chunks = shard_hosts(hosts, len(targets))
    targets = targets[: len(chunks)]

    task_history_ids: list[int] = []
    payload_uri = f"file://{_TOPOLOGY_PAYLOAD_PATH}"
    extras = {
        "connect_timeout": body.connect_timeout,
        "read_timeout": body.read_timeout,
    }
    for target, chunk in zip(targets, chunks, strict=True):
        meta = build_topology_meta(target=target, hosts=chunk, extra=extras)
        meta.setdefault("requirements", TOPOLOGY_PAYLOAD_REQUIREMENTS)
        created = await tasks_api.post(
            f"/execute/{_TOPOLOGY_TASK}",
            json={"meta": meta, "payload": payload_uri, "anonymize_mask": 0},
        )
        if not isinstance(created, dict) or "id" not in created:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Tasks API did not return a task history id.",
            )
        task_history_ids.append(int(created["id"]))
    logger.info(
        "Dispatched topology collection: hosts=%d shards=%d targets=%s tasks=%s",
        len(hosts),
        len(targets),
        targets,
        task_history_ids,
    )
    return TopologyCollectResponse(
        task_history_ids=task_history_ids,
        targets=targets,
        host_count=len(hosts),
        shard_count=len(targets),
    )


def _parse_ids_param(ids: str) -> list[int]:
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required ?ids= query parameter.",
        )
    parsed: list[int] = []
    seen: set[int] = set()
    for raw_chunk in ids.split(","):
        chunk = raw_chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid task history id: {chunk!r}.",
            ) from exc
        if value not in seen:
            seen.add(value)
            parsed.append(value)
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No task history ids provided.",
        )
    return parsed


async def _fetch_task_history(tasks_api: Any, task_history_id: int) -> dict[str, Any]:
    return await tasks_api.get(f"/history/{task_history_id}")



@router.get("/{entity}/")
async def inventory_list_entity(
    request: Request,
    entity: str,
    inventory_api: InventoryAPI,
) -> list[Any]:
    """List inventory nodes, services, schemas, or tables."""
    entity = require_inventory_plugin_entity(entity)
    params = inventory_plugin_query_params(request)
    data = await inventory_api.get(inventory_service_list_path(entity), params=params)
    return unwrap_inventory_plugin_list_payload(data)


@router.post("/{entity}/")
async def inventory_create_entity(
    entity: str,
    inventory_api: InventoryAPI,
    body: InventoryPluginJsonObjectBody,
) -> Any:
    """Create an inventory node, service, schema, or table."""
    entity = require_inventory_plugin_entity(entity)
    inv_path = inventory_service_create_path(entity, body)
    return await inventory_api.post(inv_path, json=body)


@router.get("/{entity}/{item_id:int}")
async def inventory_get_entity(
    entity: str,
    item_id: int,
    inventory_api: InventoryAPI,
) -> Any:
    """Retrieve a single inventory node, service, schema, or table."""
    entity = require_inventory_plugin_entity(entity)
    return await inventory_api.get(inventory_service_detail_path(entity, item_id))


@router.put("/{entity}/{item_id:int}")
async def inventory_update_entity(
    entity: str,
    item_id: int,
    inventory_api: InventoryAPI,
    body: InventoryPluginJsonObjectBody,
) -> Any:
    """Update an inventory node, service, schema, or table."""
    entity = require_inventory_plugin_entity(entity)
    return await inventory_api.put(
        inventory_service_detail_path(entity, item_id), json=body
    )


@router.delete("/{entity}/{item_id:int}")
async def inventory_delete_entity(
    entity: str,
    item_id: int,
    inventory_api: InventoryAPI,
) -> Response:
    """Delete an inventory node, service, schema, or table."""
    entity = require_inventory_plugin_entity(entity)
    await inventory_api.delete(inventory_service_detail_path(entity, item_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
