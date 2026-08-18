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

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Request, Response, status

from app.core.exceptions import HTTPBadRequestException
from app.core.pagination import (
    build_proxied_page,
    PaginatedResponse,
    PaginationDep,
)
from app.sep.apps.framework.api import schema_endpoint
from app.sep.apps.inventory.connectivity import probe_service_connectivity
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
    PluginTaskResponse,
)
from app.sep.apps.inventory.schema import inventory_schema
from app.sep.apps.inventory.sync import run_inventory_sync
from app.sep.crud import SyncItemManager
from app.sep.deps import (
    CreatedServiceDep,
    InventoryAPI,
    IsApiAdmin,
    SessionDep,
    TaskAPI,
)
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.connectivity.models import ConnectivityCheckResponse

router = APIRouter()
schema_endpoint(router=router, plugin_schema=inventory_schema)

# Module-level singleton avoids the B008 lint warning about function calls in
# argument defaults; the optional-body semantics are unchanged.
_OPTIONAL_TRIGGER_BODY = Body(default=None)


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
    pagination: PaginationDep,
) -> PaginatedResponse[Any]:
    """List inventory nodes, services, schemas, or tables.

    :param request: Inbound request; its query string carries entity filters.
    :param entity: Inventory entity type (nodes, services, schemas, tables).
    :param inventory_api: Async client for the Inventory sub-app.
    :param pagination: Validated offset/limit forwarded to the upstream call.
    :return: A paginated envelope echoing the requested window.
    """
    entity = require_inventory_plugin_entity(entity)
    params = inventory_plugin_query_params(request)
    params["offset"] = pagination.offset
    params["limit"] = pagination.limit
    data = await inventory_api.get(inventory_service_list_path(entity), params=params)
    items = unwrap_inventory_plugin_list_payload(data)
    envelope = data if isinstance(data, dict) else {}
    return build_proxied_page(items, envelope, pagination, client_side_filtered=False)


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


@router.post(
    "/services/{service_id:int}/check-connectivity/",
    dependencies=[IsApiAdmin],
)
async def inventory_service_check_connectivity(
    service: CreatedServiceDep,
    tasks_api: TaskAPI,
) -> ConnectivityCheckResponse:
    """Run a database connectivity probe for a service from its executor host.

    Backs the React connectivity control on the service detail page. A probe
    that ran but could not connect is reported as HTTP 200 with
    ``success=false`` and the upstream message in ``error``; only a probe that
    could not be attempted at all is an error status. This three-segment
    literal path cannot collide with the two-segment
    ``/{entity}/{item_id:int}`` detail matcher.

    :param service: The service to probe, resolved from the path id.
    :param tasks_api: Authenticated Tasks ``RemoteAPI`` client.
    :return: The upstream probe result.
    :raises HTTPBadRequestException: When the service cannot be probed —
        unsupported type, missing node or port, or no executor registered for
        the node address.
    :raises HTTPBadGatewayException: When the Tasks API is unreachable or
        returns an unparseable body.
    """
    return await probe_service_connectivity(service, tasks_api)


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
