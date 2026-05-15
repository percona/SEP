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

In addition to CRUD, this router mounts the ad-hoc inventory-sync trigger
(``POST /sync/``) and the running-state polling endpoint
(``GET /sync/status/``) consumed by the React inventory sync control. Periodic
``/schedule/`` and node/service/schema-scoped sync routes remain on the Jinja2
router for now and are owned by SEP-1141 / a Wave 3 follow-up; do not mount
them here without coordinating with those tickets. The inventory service
remains the canonical CRUD surface at ``/api/inventory/*``; this router is the
typed entry point for the React plugin.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Request, Response, status

from app.core.exceptions import HTTPBadRequestException
from app.sep.crud import SyncItemManager
from app.sep.deps import ApiCurrentUser, InventoryAPI, SessionDep
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.inventory.deps import (
    filter_syncers_by_name,
    inventory_plugin_query_params,
    inventory_service_create_path,
    inventory_service_detail_path,
    inventory_service_list_path,
    InventoryPluginJsonObjectBody,
    InventorySyncStatusResponse,
    InventorySyncTriggerWrite,
    require_inventory_plugin_entity,
    SyncersDep,
    unwrap_inventory_plugin_list_payload,
)
from app.sep.plugins.inventory.schema import inventory_schema
from app.sep.plugins.inventory.sync import run_inventory_sync

router = APIRouter()
schema_endpoint(router=router, plugin_schema=inventory_schema)

# Module-level singleton avoids the B008 lint warning about function calls in
# argument defaults; the optional-body semantics are unchanged.
_OPTIONAL_TRIGGER_BODY = Body(default=None)


@router.post("/sync/", status_code=status.HTTP_202_ACCEPTED, response_class=Response)
async def inventory_sync_trigger(
    user: ApiCurrentUser,
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
    body: InventorySyncTriggerWrite | None = _OPTIONAL_TRIGGER_BODY,
) -> Response:
    """Schedule an ad-hoc inventory sync as a background task.

    Mirrors the Jinja2 ``POST /inventory/sync/`` handler but accepts an
    optional JSON body ``{"syncer": "<qualified_name>"}``. When ``syncer``
    is absent, ``None``, or empty, every configured syncer runs in
    declaration order; otherwise only the named syncer is forwarded. An
    unknown or inapplicable syncer raises HTTP 400 — never a silent no-op.

    :param user: Current API-authenticated user; the access token is
        forwarded to the background task.
    :type user: ApiCurrentUser
    :param syncers: Configured syncers from ``SyncersDep``.
    :type syncers: SyncersDep
    :param background_tasks: FastAPI's background task scheduler.
    :type background_tasks: BackgroundTasks
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
    background_tasks.add_task(run_inventory_sync, user.access_token, *selected)
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
