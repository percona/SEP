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

"""Define routes for the Inventory Plugin."""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.sep.config import sep_settings
from app.sep.crud import SyncItemManager
from app.sep.deps import (
    CreatedNodeDep,
    CreatedSchemaDep,
    CreatedServiceDep,
    CreatedTableDep,
    CurrentUser,
    DefaultContext,
    InventoryAPI,
    IsAuthenticated,
    IsCsrfValidated,
    SessionDep,
    TaskAPI,
)
from app.sep.inventory import Node, Schema, Service, SourceEnum, Table
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.inventory.deps import SyncersDep
from app.sep.plugins.inventory.sync import (
    run_inventory_sync,
    run_node_sync,
    run_schema_sync,
    run_service_sync,
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def node_list(
    session: SessionDep,
    syncers: SyncersDep,
    request: Request,
    context: DefaultContext,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """List Nodes."""
    context["inventory"] = await inventory_api.get("/")
    context["source_enum"] = SourceEnum
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.INVENTORY,
    )
    context["can_sync"] = any(syncer.can_sync_inventory() for syncer in syncers)
    periodic_tasks = await tasks_api.get("/periodic/")
    sync_schedule = next(
        (pt for pt in periodic_tasks if pt.get("task") == "inventory-sync"),
        None,
    )
    context["sync_schedule"] = sync_schedule
    return templates.TemplateResponse(
        request=request,
        name="inventory/node-list.html.j2",
        context=context,
    )


@router.post("/sync/", dependencies=[IsAuthenticated, IsCsrfValidated])
async def sync_inventory(
    user: CurrentUser,
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Start inventory sync as a background task."""
    background_tasks.add_task(run_inventory_sync, user.access_token, *syncers)
    return RedirectResponse("/inventory/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{node_id}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def node_detail(
    session: SessionDep,
    syncers: SyncersDep,
    request: Request,
    node: CreatedNodeDep,
    context: DefaultContext,
) -> HTMLResponse:
    """Retrieve Node Details."""
    context["node"] = node
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.NODE,
    )
    context["can_sync"] = any(syncer.can_sync_node(node) for syncer in syncers)
    return templates.TemplateResponse(
        request=request,
        name="inventory/node-detail.html.j2",
        context=context,
    )


@router.post("/{node_id}/sync/", dependencies=[IsAuthenticated, IsCsrfValidated])
async def sync_node(
    user: CurrentUser,
    node: CreatedNodeDep,
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Start node sync as a background task."""
    background_tasks.add_task(run_node_sync, node, user.access_token, *syncers)
    return RedirectResponse(
        f"/inventory/{node.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/", dependencies=[IsAuthenticated, IsCsrfValidated])
async def node_create(
    inventory_api: InventoryAPI,
    node_data: Annotated[Node, Form()],
) -> RedirectResponse:
    """Create Node."""
    await inventory_api.post("/", json=node_data.model_dump(exclude={"services"}))
    return RedirectResponse("/inventory/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{node_id}/delete", dependencies=[IsAuthenticated, IsCsrfValidated])
async def node_delete(
    node_id: int,
    inventory_api: InventoryAPI,
) -> RedirectResponse:
    """Delete Node."""
    await inventory_api.delete(f"/{node_id}")
    return RedirectResponse("/inventory/", status_code=status.HTTP_303_SEE_OTHER)


@router.get(
    "/services/{service_id}",
    dependencies=[IsAuthenticated],
    response_class=HTMLResponse,
)
async def service_detail(
    session: SessionDep,
    syncers: SyncersDep,
    request: Request,
    service: CreatedServiceDep,
    context: DefaultContext,
) -> HTMLResponse:
    """Retrieve Service Details."""
    context["service"] = service
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.SERVICE,
    )
    context["can_sync"] = any(syncer.can_sync_service(service) for syncer in syncers)
    return templates.TemplateResponse(
        request=request,
        name="inventory/service-detail.html.j2",
        context=context,
    )


@router.post(
    "/services/{service_id}/sync/", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def sync_service(
    user: CurrentUser,
    service: CreatedServiceDep,
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Start service sync as a background task."""
    background_tasks.add_task(run_service_sync, service, user.access_token, *syncers)
    return RedirectResponse(
        f"/inventory/services/{service.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{node_id}/services/", dependencies=[IsAuthenticated, IsCsrfValidated])
async def service_create_for_node(
    node_id: int,
    inventory_api: InventoryAPI,
    service_data: Annotated[Service, Form()],
) -> RedirectResponse:
    """Create Service for Node."""
    await inventory_api.post(
        f"/{node_id}/services/",
        json=service_data.model_dump(exclude={"schemas"}),
    )
    return RedirectResponse(
        f"/inventory/{node_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/services/{service_id}/delete", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def service_delete(
    inventory_api: InventoryAPI,
    service: CreatedServiceDep,
) -> RedirectResponse:
    """Delete Service."""
    await inventory_api.delete(f"/services/{service.id}")
    return RedirectResponse(
        f"/inventory/{service.node_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/schemas/{schema_id}",
    dependencies=[IsAuthenticated],
    response_class=HTMLResponse,
)
async def schema_detail(
    session: SessionDep,
    syncers: SyncersDep,
    request: Request,
    schema: CreatedSchemaDep,
    context: DefaultContext,
) -> HTMLResponse:
    """Retrieve Schema Details."""
    context["schema"] = schema
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.SCHEMA,
    )
    context["can_sync"] = any(syncer.can_sync_schema(schema) for syncer in syncers)
    return templates.TemplateResponse(
        request=request,
        name="inventory/schema-detail.html.j2",
        context=context,
    )


@router.post(
    "/schemas/{schema_id}/sync/", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def sync_schema(
    user: CurrentUser,
    schema: CreatedSchemaDep,
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Start schema sync as a background task."""
    background_tasks.add_task(run_schema_sync, schema, user.access_token, *syncers)
    return RedirectResponse(
        f"/inventory/schemas/{schema.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/services/{service_id}/schemas/", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def schema_create_for_service(
    service_id: int,
    inventory_api: InventoryAPI,
    schema_data: Annotated[Schema, Form()],
) -> RedirectResponse:
    """Create Schema for Service."""
    await inventory_api.post(
        f"/services/{service_id}/schemas/",
        json=schema_data.model_dump(exclude={"tables"}),
    )
    return RedirectResponse(
        f"/inventory/services/{service_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/schemas/{schema_id}/delete", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def schema_delete(
    inventory_api: InventoryAPI,
    schema: CreatedSchemaDep,
) -> RedirectResponse:
    """Delete Schema."""
    await inventory_api.delete(f"/schemas/{schema.id}")
    return RedirectResponse(
        f"/inventory/services/{schema.service_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/schemas/{schema_id}/tables/", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def table_create_for_schema(
    schema_id: int,
    inventory_api: InventoryAPI,
    table_data: Annotated[Table, Form()],
) -> RedirectResponse:
    """Create Table for Schema."""
    await inventory_api.post(
        f"/schemas/{schema_id}/tables/",
        json=table_data.model_dump(),
    )
    return RedirectResponse(
        f"/inventory/schemas/{schema_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/tables/{table_id}/delete", dependencies=[IsAuthenticated, IsCsrfValidated]
)
async def table_delete(
    inventory_api: InventoryAPI,
    table: CreatedTableDep,
) -> RedirectResponse:
    """Delete Table."""
    await inventory_api.delete(f"/tables/{table.id}")
    return RedirectResponse(
        f"/inventory/schemas/{table.schema_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
