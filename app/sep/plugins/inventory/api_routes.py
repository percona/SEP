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
``app/sep/api/router.py``. Authentication is enforced at the ``api_router``
level; the ``schema_endpoint`` helper also pins ``IsApiAuthenticated`` per
route for safety.

Proxies CRUD for nodes, services, schemas, and tables to the inventory HTTP API
through ``InventoryAPI`` in ``app.sep.deps`` (``RemoteAPI`` toward the
inventory service). List handlers unwrap paginated ``items`` into a JSON array
for the schema-driven React client.

Schedule and periodic sync routes are not mounted here so SEP-1058 can own the
React schedule UI; do not add schedule or inventory-sync proxy routes without
coordinating with that ticket. The inventory service remains the canonical CRUD
surface at ``/api/inventory/*``; this router is the typed entry point for the
React plugin.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.exceptions import HTTPUnprocessableEntityException
from app.sep.deps import InventoryAPI
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.inventory.deps import (
    inventory_plugin_query_params,
    inventory_service_create_path,
    inventory_service_detail_path,
    inventory_service_list_path,
    require_inventory_plugin_entity,
    unwrap_inventory_plugin_list_payload,
)
from app.sep.plugins.inventory.schema import inventory_schema

router = APIRouter()
schema_endpoint(router=router, plugin_schema=inventory_schema)


def _inventory_list_redirect_url(request: Request) -> str:
    """Build ``GET /…/{entity}/`` URL preserving query string and fragment.

    Starlette's ``URL.replace(path=…)`` can mishandle query strings for this
    redirect; splitting with ``urlsplit`` ensures the slash is appended to the
    path before ``?limit=…`` is reattached (e.g. ``…/nodes/?limit=10``).
    """
    parts = urlsplit(str(request.url))
    new_path = parts.path.rstrip("/") + "/"
    return urlunsplit(
        (parts.scheme, parts.netloc, new_path, parts.query, parts.fragment)
    )


@router.get("/{entity}")
async def inventory_entity_redirect_slash(
    request: Request, entity: str
) -> RedirectResponse:
    """Redirect ``GET /{entity}`` to ``GET /{entity}/`` for list routes."""
    require_inventory_plugin_entity(entity)
    return RedirectResponse(
        url=_inventory_list_redirect_url(request),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


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
    request: Request,
) -> Any:
    """Create an inventory node, service, schema, or table."""
    entity = require_inventory_plugin_entity(entity)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPUnprocessableEntityException("JSON object body required")
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
    request: Request,
) -> Any:
    """Update an inventory node, service, schema, or table."""
    entity = require_inventory_plugin_entity(entity)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPUnprocessableEntityException("JSON object body required")
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
