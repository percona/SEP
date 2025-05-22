"""Define routes for the Inventory Plugin."""

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.sep.config import sep_settings
from app.sep.deps import (
    CreatedNodeDep,
    CreatedSchemaDep,
    CreatedServiceDep,
    CreatedTableDep,
    DefaultContext,
    InventoryAPI,
    IsAuthenticated,
    IsCsrfValidated,
)
from app.sep.inventory import Node, Schema, Service, Table
from app.sep.plugins.inventory.deps import (
    NodeDetailContextDep,
    NodesContextDep,
    SchemaDetailContextDep,
    ServiceDetailContextDep,
    SyncersDep,
)
from app.sep.plugins.inventory.sync import (
    run_inventory_sync,
    run_node_sync,
    run_schema_sync,
    run_service_sync,
)

from .api.routes import router as inventory_api_router

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES

router.include_router(inventory_api_router, prefix="/api", tags=["inventory-api"])


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def node_list(
    request: Request, context: DefaultContext, nodes_context: NodesContextDep
) -> HTMLResponse:
    """List Nodes."""
    context.update(nodes_context)
    return templates.TemplateResponse(
        request=request,
        name="inventory/node-list.html",
        context=context,
    )


@router.post("/sync/", dependencies=[IsAuthenticated, IsCsrfValidated])
async def sync_inventory(
    syncers: SyncersDep,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Start inventory sync as a background task."""
    background_tasks.add_task(run_inventory_sync, *syncers)
    return RedirectResponse("/inventory/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{node_id}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def node_detail(
    request: Request,
    node_detail_context: NodeDetailContextDep,
    context: DefaultContext,
) -> HTMLResponse:
    """Retrieve Node Details."""
    context.update(node_detail_context)
    return templates.TemplateResponse(
        request=request,
        name="inventory/node-detail.html",
        context=context,
    )


@router.post("/{node_id}/sync/", dependencies=[IsAuthenticated, IsCsrfValidated])
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
    request: Request,
    service_detail_context: ServiceDetailContextDep,
    context: DefaultContext,
) -> HTMLResponse:
    """Retrieve Service Details."""
    context.update(service_detail_context)
    return templates.TemplateResponse(
        request=request,
        name="inventory/service-detail.html",
        context=context,
    )


@router.post(
    "/services/{service_id}/sync", dependencies=[IsAuthenticated, IsCsrfValidated]
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
    request: Request,
    schema_detail_context: SchemaDetailContextDep,
    context: DefaultContext,
) -> HTMLResponse:
    """Retrieve Schema Details."""
    context.update(schema_detail_context)
    return templates.TemplateResponse(
        request=request,
        name="inventory/schema-detail.html",
        context=context,
    )


@router.post(
    "/schemas/{schema_id}/sync", dependencies=[IsAuthenticated, IsCsrfValidated]
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
