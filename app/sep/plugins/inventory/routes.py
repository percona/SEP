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
    DefaultContext,
    InventoryAPI,
    IsAuthenticated,
    SessionDep,
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
) -> HTMLResponse:
    """List Nodes."""
    context["csrf_token"] = request.state.csrf_token
    context["inventory"] = await inventory_api.get("/")
    context["source_enum"] = SourceEnum
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.INVENTORY,
    )
    context["can_sync"] = any(syncer.can_sync_inventory() for syncer in syncers)
    return templates.TemplateResponse(
        request=request,
        name="inventory/node-list.html",
        context=context,
    )


@router.post("/sync/", dependencies=[IsAuthenticated])
async def sync_inventory(
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Start inventory sync as a background task."""
    background_tasks.add_task(run_inventory_sync, *syncers)
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
    context["csrf_token"] = request.state.csrf_token
    context["node"] = node
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.NODE,
    )
    context["can_sync"] = any(syncer.can_sync_node(node) for syncer in syncers)
    return templates.TemplateResponse(
        request=request,
        name="inventory/node-detail.html",
        context=context,
    )


@router.post("/{node_id}/sync/", dependencies=[IsAuthenticated])
async def sync_node(
    node: CreatedNodeDep,
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Start node sync as a background task."""
    background_tasks.add_task(run_node_sync, node, *syncers)
    return RedirectResponse(
        f"/inventory/{node.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/", dependencies=[IsAuthenticated])
async def node_create(
    inventory_api: InventoryAPI,
    node_data: Annotated[Node, Form()],
) -> RedirectResponse:
    """Create Node."""
    await inventory_api.post("/", json=node_data.model_dump(exclude={"services"}))
    return RedirectResponse("/inventory/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{node_id}/delete", dependencies=[IsAuthenticated])
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
    context["csrf_token"] = request.state.csrf_token
    context["service"] = service
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.SERVICE,
    )
    context["can_sync"] = any(syncer.can_sync_service(service) for syncer in syncers)
    return templates.TemplateResponse(
        request=request,
        name="inventory/service-detail.html",
        context=context,
    )


@router.post(
    "/services/{service_id}/sync/", dependencies=[IsAuthenticated]
)
async def sync_service(
    service: CreatedServiceDep,
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Start service sync as a background task."""
    background_tasks.add_task(run_service_sync, service, *syncers)
    return RedirectResponse(
        f"/inventory/services/{service.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{node_id}/services/", dependencies=[IsAuthenticated])
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
    "/services/{service_id}/delete", dependencies=[IsAuthenticated]
)
async def service_delete(
    service_id: int,
    inventory_api: InventoryAPI,
) -> RedirectResponse:
    """Delete Service."""
    response = await inventory_api.delete(f"/services/{service_id}")
    node_id = response["node_id"]
    return RedirectResponse(
        f"/inventory/{node_id}",
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
    context["csrf_token"] = request.state.csrf_token
    context["schema"] = schema
    context["sync_is_running"] = await SyncItemManager.sync_is_running(
        session,
        SyncInventoryEntityTypeEnum.SCHEMA,
    )
    context["can_sync"] = any(syncer.can_sync_schema(schema) for syncer in syncers)
    return templates.TemplateResponse(
        request=request,
        name="inventory/schema-detail.html",
        context=context,
    )


@router.post(
    "/schemas/{schema_id}/sync/", dependencies=[IsAuthenticated]
)
async def sync_schema(
    schema: CreatedSchemaDep,
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Start schema sync as a background task."""
    background_tasks.add_task(run_schema_sync, schema, *syncers)
    return RedirectResponse(
        f"/inventory/schemas/{schema.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/services/{service_id}/schemas/", dependencies=[IsAuthenticated]
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
    "/schemas/{schema_id}/delete", dependencies=[IsAuthenticated]
)
async def schema_delete(
    schema_id: int,
    inventory_api: InventoryAPI,
) -> RedirectResponse:
    """Delete Schema."""
    response = await inventory_api.delete(f"/schemas/{schema_id}")
    service_id = response["service_id"]
    return RedirectResponse(
        f"/inventory/services/{service_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/schemas/{schema_id}/tables/", dependencies=[IsAuthenticated]
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
    "/tables/{table_id}/delete", dependencies=[IsAuthenticated]
)
async def table_delete(
    table_id: int,
    inventory_api: InventoryAPI,
) -> RedirectResponse:
    """Delete Table."""
    response = await inventory_api.delete(f"/tables/{table_id}")
    schema_id = response["schema_id"]
    return RedirectResponse(
        f"/inventory/schemas/{schema_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
