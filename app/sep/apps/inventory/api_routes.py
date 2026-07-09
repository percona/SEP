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

Mounted at ``/api/apps/inventory/`` via ``apps_router`` in
``app/sep/api/router.py``. Like other plugin proxies, these routes rely on the
parent ``api_router`` for API authentication. The ``schema_endpoint`` helper
additionally attaches ``IsApiAuthenticated`` to the schema route only; list,
detail, create, update, and delete handlers do not duplicate that dependency.

Proxies CRUD for nodes, services, schemas, and tables to the inventory HTTP API
through ``InventoryAPI`` in ``app.sep.deps`` (``RemoteAPI`` toward the
inventory service). List handlers unwrap paginated ``items`` into a JSON array
for the schema-driven React client. POST and PUT bodies are parsed with the
``InventoryPluginJsonObjectBody`` in ``app.sep.apps.inventory.deps`` (see
``inventory_plugin_json_object_body``) so non-object JSON consistently yields
HTTP 422.

In addition to CRUD, this router mounts the ad-hoc inventory-sync trigger
(``POST /sync/``) and the running-state polling endpoint
(``GET /sync/status/``) consumed by the React inventory sync control. Schedule
discovery (``GET /``) and available-syncers (``GET /available-syncers/``) are
also mounted here so the React schedule UI can fetch its data
through the plugin API gateway. Periodic-task CRUD remains delegated to
``/api/tasks/periodic/*`` as the single source of truth; this router does not
duplicate that surface. The inventory service remains the canonical CRUD
surface at ``/api/inventory/*``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import StreamingResponse

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.exceptions import (
    HTTPBadGatewayException,
    HTTPBadRequestException,
    HTTPNotFoundException,
    HTTPServiceUnavailableException,
)
from app.core.requests import RemoteAPI
from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.config import sep_settings
from app.sep.crud import SyncItemManager
from app.sep.deps import (
    ApiCurrentUser,
    InventoryAPI,
    IsApiAuthenticated,
    IsCsrfValidated,
    SessionDep,
    TaskAPI,
)
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.apps.framework.schema import Capabilities, PluginSchema
from app.sep.apps.inventory import payloads
from app.sep.apps.inventory.deps import (
    AvailableSyncer,
    filter_syncers_by_name,
    InternalTokenDep,
    inventory_plugin_query_params,
    inventory_service_create_path,
    inventory_service_detail_path,
    inventory_service_list_path,
    inventory_system_observation_path,
    InventoryAvailableSyncersDep,
    InventoryPluginJsonObjectBody,
    InventorySyncStatusResponse,
    InventorySyncTriggerWrite,
    require_inventory_plugin_entity,
    SyncersDep,
    SYSTEM_OBSERVATION_SEGMENT,
    unwrap_inventory_plugin_list_payload,
)
from app.sep.apps.inventory.models import (
    INVENTORY_SYNC_TASK_NAME,
    MAX_TOPOLOGY_SHARDS,
    PluginTaskResponse,
    TopologyCollectResponse,
    TopologyCollectWrite,
    TopologyResultResponse,
)
from app.sep.apps.inventory.schema import inventory_schema
from app.sep.apps.inventory.sync import run_inventory_sync
from app.sep.apps.inventory.topology import (
    build_graph_from_stdouts,
    build_topology_meta,
    parse_ndjson,
    shard_hosts,
    TOPOLOGY_JOB_PREFIX,
)
from app.tasks.models import TaskHistoryStatusEnum

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level singleton avoids the B008 lint warning about function calls in
# argument defaults; the optional-body semantics are unchanged.
_OPTIONAL_TRIGGER_BODY = Body(default=None)


@router.get(
    "/schema",
    response_model=PluginSchema,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    dependencies=[IsApiAuthenticated],
)
async def get_schema() -> PluginSchema:
    """Return the inventory plugin schema with deployment-time capabilities."""
    return inventory_schema.model_copy(
        update={
            "capabilities": (
                inventory_schema.capabilities or Capabilities()
            ).model_copy(
                update={"topology": sep_settings.INVENTORY_TOPOLOGY_ENABLED},
            )
        },
    )


@router.post("/sync/", status_code=status.HTTP_202_ACCEPTED, response_class=Response)
async def inventory_sync_trigger(
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
    internal_token: InternalTokenDep,
    body: InventorySyncTriggerWrite | None = _OPTIONAL_TRIGGER_BODY,
) -> Response:
    """Schedule an ad-hoc inventory sync as a background task.

    Mirrors the Jinja2 ``POST /inventory/sync/`` handler but accepts an
    optional JSON body ``{"syncer": "<qualified_name>"}``. When ``syncer``
    is absent, ``None``, or empty, every configured syncer runs in
    declaration order; otherwise only the named syncer is forwarded. An
    unknown or inapplicable syncer raises HTTP 400 — never a silent no-op.

    Authentication is enforced by the parent ``api_router``'s
    ``IsApiAuthenticated`` dependency, so this handler needs no auth parameter.

    :param syncers: Configured syncers from ``SyncersDep``.
    :type syncers: SyncersDep
    :param background_tasks: FastAPI's background task scheduler.
    :type background_tasks: BackgroundTasks
    :param internal_token: SEP-internal service token injected by
        ``InternalTokenDep`` and forwarded to the background sync task.
    :param body: Optional trigger body.
    :type body: InventorySyncTriggerWrite | None
    :return: Empty 202 Accepted response.
    :rtype: Response
    :raises HTTPBadRequestException: When ``body.syncer`` is set but does
        not match any configured syncer that can sync inventory.
    """
    syncer_name = body.syncer if body is not None else None
    try:
        selected = filter_syncers_by_name(
            syncers,
            syncer_name,
            lambda syncer: syncer.can_sync_inventory(),
        )
    except ValueError as exc:
        raise HTTPBadRequestException(str(exc)) from exc
    background_tasks.add_task(run_inventory_sync, internal_token, *selected)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.get("/sync/status/")
async def inventory_sync_status(session: SessionDep) -> InventorySyncStatusResponse:
    """Return whether an inventory-wide sync is currently running.

    Replaces the server-rendered ``sync_is_running`` template variable
    used by the Jinja2 inventory page so the React control can poll the
    same state without scraping HTML.

    :param session: SQLModel async session.
    :type session: SessionDep
    :return: ``{"is_running": <bool>}``.
    :rtype: InventorySyncStatusResponse
    """
    is_running = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.INVENTORY,
    )
    return InventorySyncStatusResponse(is_running=is_running)


_TOPOLOGY_PAYLOAD_PATH = Path(payloads.__file__).parent / "topology.py"
_TOPOLOGY_TASK = "run-python"
_TOPOLOGY_STDOUT_STEP = "run-script"
_TOPOLOGY_HEARTBEAT_SECONDS = 15.0
_TOPOLOGY_POLL_INTERVAL_SECONDS = 0.5


def _require_topology_enabled() -> None:
    """Reject topology API access while the feature flag is off."""
    if not sep_settings.INVENTORY_TOPOLOGY_ENABLED:
        raise HTTPNotFoundException("Inventory topology is disabled.")


def _format_host_entry(service: dict[str, Any]) -> str | None:
    """Return a collector ``host:port`` entry for an inventory service.

    :param service: Inventory service payload with optional nested node data.
    :type service: dict[str, Any]
    :return: ``address:port`` or ``name:port`` when address data exists.
    :rtype: str | None
    """
    node = service.get("node") or {}
    address = node.get("address") or service.get("name")
    if address:
        port = service.get("port") or DEFAULT_MYSQL_PORT
        return f"{address}:{port}"
    return None


async def _collect_mysql_host_entries(inventory_api: RemoteAPI) -> list[str]:
    """Return ``host:port`` entries for every MySQL service in inventory.

    :param inventory_api: Remote inventory API client.
    :type inventory_api: RemoteAPI
    :return: De-duplicated MySQL ``host:port`` entries in inventory order.
    :rtype: list[str]
    """
    response = await inventory_api.get(
        "/services/", params={"service_type": ServiceTypeEnum.MYSQL.value, "limit": 0}
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
    """Select executor host names for topology collection.

    :param available_hosts: Mapping of executor host names to host addresses.
    :type available_hosts: dict[str, str]
    :param requested_executor: Optional explicit executor host name.
    :type requested_executor: str | None
    :param shards: Requested number of executor shards.
    :type shards: int
    :return: Selected executor host names.
    :rtype: list[str]
    :raises HTTPServiceUnavailableException: When no executor hosts are available.
    :raises HTTPBadRequestException: When the explicit executor is unavailable.
    """
    if not available_hosts:
        raise HTTPServiceUnavailableException(
            "No executor hosts available for topology collection.",
        )
    if requested_executor:
        if requested_executor not in available_hosts:
            raise HTTPBadRequestException(
                f"Executor host {requested_executor!r} is not available.",
            )
        return [requested_executor]
    return list(available_hosts.keys())[:shards]


@router.post(
    "/topology/collect",
    dependencies=[IsCsrfValidated],
    response_model=TopologyCollectResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def topology_collect(
    body: TopologyCollectWrite,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> TopologyCollectResponse:
    """Dispatch one or more topology collector tasks. Returns the task ids.

    Hosts are pulled from the inventory MySQL service list; no inventory
    persistence side effects occur. With ``shards > 1`` the host list is
    split round-robin across the first N executor hosts so geographically
    split inventories run in parallel.
    """
    _require_topology_enabled()
    hosts = await _collect_mysql_host_entries(inventory_api)
    if not hosts:
        raise HTTPNotFoundException(
            "No MySQL services found in inventory.",
        )
    available_hosts = await tasks_api.get("/hosts/")
    if not isinstance(available_hosts, dict):
        raise HTTPBadGatewayException(
            "Tasks API returned an invalid executor hosts payload.",
        )
    targets = _select_topology_targets(available_hosts, body.executor_host, body.shards)
    chunks = shard_hosts(hosts, len(targets))
    targets = targets[: len(chunks)]

    payload_uri = f"file://{_TOPOLOGY_PAYLOAD_PATH}"
    extras = {
        "connect_timeout": body.connect_timeout,
        "read_timeout": body.read_timeout,
    }
    dispatches = []
    for target, chunk in zip(targets, chunks, strict=True):
        meta = build_topology_meta(target=target, hosts=chunk, extra=extras)
        dispatches.append(
            tasks_api.post(
                f"/execute/{_TOPOLOGY_TASK}",
                json={"meta": meta, "payload": payload_uri, "anonymize_mask": 0},
            )
        )

    created_tasks = await asyncio.gather(*dispatches)
    task_history_ids: list[int] = []
    for created in created_tasks:
        if not isinstance(created, dict) or "id" not in created:
            raise HTTPBadGatewayException(
                "Tasks API did not return a task history id.",
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
        raise HTTPBadRequestException("Missing required ?ids= query parameter.")
    parsed: list[int] = []
    seen: set[int] = set()
    for raw_chunk in ids.split(","):
        chunk = raw_chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError as exc:
            raise HTTPBadRequestException(
                f"Invalid task history id: {chunk!r}."
            ) from exc
        if value not in seen:
            seen.add(value)
            parsed.append(value)
    if not parsed:
        raise HTTPBadRequestException("No task history ids provided.")
    if len(parsed) > MAX_TOPOLOGY_SHARDS:
        raise HTTPBadRequestException(
            f"At most {MAX_TOPOLOGY_SHARDS} task history ids are allowed."
        )
    return parsed


async def _fetch_task_history(
    tasks_api: RemoteAPI, task_history_id: int
) -> dict[str, Any]:
    return await tasks_api.get(f"/history/{task_history_id}")


def _is_inventory_topology_history(
    history: dict[str, Any], current_user_id: str
) -> bool:
    execution_request = history.get("execution_request") or {}
    meta = execution_request.get("meta") or {}
    return (
        history.get("executed_by") == current_user_id
        and execution_request.get("task") == _TOPOLOGY_TASK
        and meta.get("_job_id_prefix") == TOPOLOGY_JOB_PREFIX
    )


def _require_inventory_topology_histories(
    histories: list[dict[str, Any]], current_user: ApiCurrentUser
) -> None:
    """Reject task histories not dispatched by this user for inventory topology."""
    current_user_id = str(current_user.id)
    if not all(_is_inventory_topology_history(h, current_user_id) for h in histories):
        raise HTTPForbiddenException("Task history is not accessible.")


async def _fetch_task_stdout(tasks_api: RemoteAPI, task_history_id: int) -> str:
    """Fetch and concatenate the stdout payload for a finished task history."""
    output: list[str] = []
    async for chunk in tasks_api.stream(
        f"/history/{task_history_id}/logs/", params={"step": _TOPOLOGY_STDOUT_STEP}
    ):
        if not chunk:
            continue
        try:
            log_entry = json.loads(chunk)
        except json.JSONDecodeError:
            logger.debug("Non-JSON log line from task %s", task_history_id)
            continue
        if log_entry.get("type") == "stdout":
            output.append(log_entry.get("msg", ""))
    return "".join(output)


def _unsuccessful_terminal_task_ids(histories: list[dict[str, Any]]) -> list[int]:
    return [
        int(h["id"])
        for h in histories
        if h.get("status") != TaskHistoryStatusEnum.SUCCESS.value
    ]


def _is_terminal_task_status(status_value: Any) -> bool:
    try:
        return TaskHistoryStatusEnum(status_value).is_terminal()
    except ValueError:
        return False


@router.get("/topology/result", response_model=TopologyResultResponse)
async def topology_result(
    tasks_api: TaskAPI,
    current_user: ApiCurrentUser,
    ids: str = Query(..., description="Comma-separated task history ids"),
) -> TopologyResultResponse:
    """Return the merged graph for the supplied task history ids.

    Status mirrors the underlying tasks: ``running`` while any are pending
    or running, ``failed`` when any task failed and produced no usable
    output, ``ok`` once every task is finished. The React client caches
    the response via TanStack Query (long ``staleTime``) and stops
    polling once status flips to ``ok``, so the server doesn't bother
    with HTTP cache validation here.
    """
    _require_topology_enabled()
    task_ids = _parse_ids_param(ids)
    histories = list(
        await asyncio.gather(*(_fetch_task_history(tasks_api, tid) for tid in task_ids))
    )
    _require_inventory_topology_histories(histories, current_user)
    pending = [
        int(h["id"]) for h in histories if not _is_terminal_task_status(h.get("status"))
    ]
    if pending:
        return TopologyResultResponse(status="running", pending_task_ids=pending)
    stdouts = list(
        await asyncio.gather(*(_fetch_task_stdout(tasks_api, tid) for tid in task_ids))
    )
    graph = build_graph_from_stdouts(stdouts)
    failed_task_ids = _unsuccessful_terminal_task_ids(histories)
    return TopologyResultResponse(
        status="failed" if failed_task_ids and not graph["nodes"] else "ok",
        graph=graph,
        failed_task_ids=failed_task_ids,
    )


def _build_sse_event(event: str, data: Any) -> str:
    payload = json.dumps(data, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


async def _put_task_error(
    queue: asyncio.Queue[dict[str, Any]],
    task_history_id: int,
    exc: HTTPException,
) -> None:
    """Queue a task-level error event for one topology shard."""
    await queue.put(
        {
            "event": "task_error",
            "data": {
                "task_history_id": task_history_id,
                "status_code": exc.status_code,
                "detail": exc.detail,
            },
        }
    )


async def _put_task_done(
    queue: asyncio.Queue[dict[str, Any]], task_history_id: int
) -> None:
    """Queue the completion marker for one topology shard worker."""
    await queue.put(
        {
            "event": "task_done",
            "data": {"task_history_id": task_history_id},
        }
    )


async def _poll_task_until_streamable(
    tasks_api: RemoteAPI,
    task_history_id: int,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    """Poll task history until logs can be streamed or task is terminal."""
    last_status: str | None = None
    while True:
        history = await _fetch_task_history(tasks_api, task_history_id)
        current = history.get("status")
        if current != last_status:
            last_status = current
            await queue.put(
                {
                    "event": "task_status",
                    "data": {
                        "task_history_id": task_history_id,
                        "status": current,
                    },
                }
            )
        if current == TaskHistoryStatusEnum.RUNNING.value or _is_terminal_task_status(
            current
        ):
            return
        await asyncio.sleep(_TOPOLOGY_POLL_INTERVAL_SECONDS)


async def _stream_task_stdout(
    tasks_api: RemoteAPI,
    task_history_id: int,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    """Parse stdout log chunks into topology events for one shard."""
    async for raw_line in tasks_api.stream(
        f"/history/{task_history_id}/logs/",
        params={"step": _TOPOLOGY_STDOUT_STEP},
    ):
        if not raw_line:
            continue
        try:
            log_entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if log_entry.get("type") != "stdout":
            continue
        msg = log_entry.get("msg", "")
        for ev in parse_ndjson(msg):
            await queue.put(
                {
                    "event": ev.get("event", "host_done"),
                    "data": {
                        "task_history_id": task_history_id,
                        **ev,
                    },
                }
            )


async def _stream_one_task(
    tasks_api: RemoteAPI, task_history_id: int, queue: asyncio.Queue[dict[str, Any]]
) -> None:
    """Tail one task's stdout NDJSON; push parsed events to ``queue``."""
    try:
        try:
            await _poll_task_until_streamable(tasks_api, task_history_id, queue)
        except HTTPException as exc:
            await _put_task_error(queue, task_history_id, exc)
            return

        try:
            await _stream_task_stdout(tasks_api, task_history_id, queue)
        except HTTPException as exc:
            await _put_task_error(queue, task_history_id, exc)
    finally:
        await _put_task_done(queue, task_history_id)


async def _topology_event_stream(
    tasks_api: RemoteAPI, task_ids: list[int]
) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    workers = [
        asyncio.create_task(_stream_one_task(tasks_api, tid, queue)) for tid in task_ids
    ]
    finished: set[int] = set()
    try:
        yield _build_sse_event(
            "ready", {"task_history_ids": task_ids, "shard_count": len(task_ids)}
        )
        while finished != set(task_ids):
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=_TOPOLOGY_HEARTBEAT_SECONDS
                )
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield _build_sse_event(event["event"], event["data"])
            if event["event"] == "task_done":
                finished.add(event["data"]["task_history_id"])
        yield _build_sse_event("complete", {"task_history_ids": task_ids})
    finally:
        for worker in workers:
            worker.cancel()
        for worker in workers:
            try:
                await worker
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Topology stream worker failed.")


@router.get("/topology/stream")
async def topology_stream(
    tasks_api: TaskAPI,
    current_user: ApiCurrentUser,
    ids: str = Query(..., description="Comma-separated task history ids"),
) -> StreamingResponse:
    """Stream per-host topology events as SSE from the supplied tasks.

    Frontend hooks (``useTopologyStream``) consume this to render the
    React Flow graph progressively as each MySQL host finishes.
    """
    _require_topology_enabled()
    task_ids = _parse_ids_param(ids)
    histories = list(
        await asyncio.gather(*(_fetch_task_history(tasks_api, tid) for tid in task_ids))
    )
    _require_inventory_topology_histories(histories, current_user)
    return StreamingResponse(
        _topology_event_stream(tasks_api, task_ids),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/")
async def inventory_plugin_tasks() -> list[PluginTaskResponse]:
    """Return the list of periodic task names for the Inventory plugin.

    Hard-coded because the Inventory plugin has exactly one periodic task
    (``inventory-sync``). The shape matches what the React
    ``usePluginTasks('inventory')`` hook expects: a list of objects with at
    minimum a ``name`` key.
    """
    return [
        PluginTaskResponse(name=INVENTORY_SYNC_TASK_NAME, display_name="Inventory Sync")
    ]


@router.get("/available-syncers/")
async def inventory_available_syncers(
    available_syncers: InventoryAvailableSyncersDep,
) -> list[AvailableSyncer]:
    """Return syncers capable of syncing inventory.

    :param available_syncers: Filtered syncer list from ``InventoryAvailableSyncersDep``.
    :type available_syncers: list[AvailableSyncer]
    :return: Filtered list of syncers that can sync inventory.
    :rtype: list[AvailableSyncer]
    """
    return available_syncers


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


@router.get(f"/nodes/{{node_id:int}}/{SYSTEM_OBSERVATION_SEGMENT}")
async def inventory_node_system_observation(
    node_id: int,
    inventory_api: InventoryAPI,
) -> Any:
    """Proxy the host-level system observation for a node (read-only).

    Forwards to the inventory sub-app's ``/nodes/{node_id}/system-observation``
    endpoint via ``InventoryAPI``. This three-segment literal path cannot
    collide with the two-segment ``/{entity}/{item_id:int}`` detail matcher. An
    upstream HTTP 404 — the "not collected yet" signal — propagates unchanged
    for the React panel to render as an empty state.

    :param node_id: Primary key of the node.
    :param inventory_api: Authenticated inventory ``RemoteAPI`` client.
    :return: The host-level system observation payload.
    """
    return await inventory_api.get(inventory_system_observation_path("nodes", node_id))


@router.get(f"/services/{{service_id:int}}/{SYSTEM_OBSERVATION_SEGMENT}")
async def inventory_service_system_observation(
    service_id: int,
    inventory_api: InventoryAPI,
) -> Any:
    """Proxy the service-level system observation for a service (read-only).

    Forwards to the inventory sub-app's
    ``/services/{service_id}/system-observation`` endpoint via ``InventoryAPI``.
    An upstream HTTP 404 propagates unchanged so the React panel renders its
    "not collected yet" empty state.

    :param service_id: Primary key of the service.
    :param inventory_api: Authenticated inventory ``RemoteAPI`` client.
    :return: The service-level system observation payload.
    """
    return await inventory_api.get(
        inventory_system_observation_path("services", service_id)
    )


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
