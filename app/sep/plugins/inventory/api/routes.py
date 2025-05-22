"""API routes for the Inventory Plugin."""

import logging

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from app.core.utils.serialization import enum_serializer
from app.sep.deps import (
    CreatedNodeDep,
    CreatedSchemaDep,
    CreatedServiceDep,
    CreatedTableDep,
    InventoryAPI,
    IsAuthenticated,
)
from app.sep.plugins.inventory.deps import (
    NodeDetailContextDep,
    NodeDetailContextResponse,
    NodesContextDep,
    SchemaDetailContextDep,
    SchemaDetailContextResponse,
    ServiceDetailContextDep,
    ServiceDetailContextResponse,
    SyncersDep,
)
from app.sep.plugins.inventory.sync import (
    run_inventory_sync,
    run_node_sync,
    run_schema_sync,
    run_service_sync,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/nodes", dependencies=[IsAuthenticated])
async def node_list_api(nodes_context: NodesContextDep) -> JSONResponse:
    """Get a list of all nodes in the inventory system."""
    nodes_context["source_enum"] = enum_serializer(nodes_context["source_enum"])
    return JSONResponse(content=nodes_context, status_code=200)


@router.post("/nodes/sync", dependencies=[IsAuthenticated])
async def sync_inventory_api(
    syncers: SyncersDep, background_tasks: BackgroundTasks
) -> JSONResponse:
    """Start a background sync of all nodes in the inventory system."""
    background_tasks.add_task(run_inventory_sync, *syncers)
    return JSONResponse(content={"status": "sync started"})


@router.get(
    "/nodes/{node_id}",
    dependencies=[IsAuthenticated],
    response_model=NodeDetailContextResponse,
)
async def node_detail_api(
    node_detail_context: NodeDetailContextDep,
) -> NodeDetailContextResponse:
    """Get detailed information about a specific node by its ID."""
    return NodeDetailContextResponse(**node_detail_context)


@router.post("/nodes/{node_id}/sync", dependencies=[IsAuthenticated])
async def sync_node_api(
    node: CreatedNodeDep, syncers: SyncersDep, background_tasks: BackgroundTasks
) -> JSONResponse:
    """Start a background sync for a specific node by its ID."""
    background_tasks.add_task(run_node_sync, node, *syncers)
    return JSONResponse(content={"status": "sync started"})


@router.post("/nodes/{node_id}/delete", dependencies=[IsAuthenticated])
async def node_delete_api(node_id: int, inventory_api: InventoryAPI) -> JSONResponse:
    """Delete a specific node from the inventory system by its ID."""
    await inventory_api.delete(f"/{node_id}")
    return JSONResponse(content={"status": f"deleted node: {node_id}"})


@router.get(
    "/services/{service_id}",
    dependencies=[IsAuthenticated],
    response_model=ServiceDetailContextResponse,
)
async def service_detail_api(
    service_detail_context: ServiceDetailContextDep,
) -> ServiceDetailContextResponse:
    """Get detailed information about a specific service by its ID."""
    return ServiceDetailContextResponse(**service_detail_context)


@router.post("/services/{service_id}/sync", dependencies=[IsAuthenticated])
async def sync_service_api(
    service: CreatedServiceDep, syncers: SyncersDep, background_tasks: BackgroundTasks
) -> JSONResponse:
    """Start a background sync for a specific service by its ID."""
    background_tasks.add_task(run_service_sync, service, *syncers)
    return JSONResponse(content={"status": "sync started"})


@router.post("/services/{service_id}/delete", dependencies=[IsAuthenticated])
async def service_delete_api(
    inventory_api: InventoryAPI, service: CreatedServiceDep
) -> JSONResponse:
    """Delete a specific service from the inventory system by its ID."""
    await inventory_api.delete(f"/services/{service.id}")
    return JSONResponse(content={"status": f"deleted service: {service.id}"})


@router.get(
    "/schemas/{schema_id}",
    dependencies=[IsAuthenticated],
    response_model=SchemaDetailContextResponse,
)
async def schema_detail_api(
    schema_detail_context: SchemaDetailContextDep,
) -> SchemaDetailContextResponse:
    """Get detailed information about a specific schema by its ID."""
    return SchemaDetailContextResponse(**schema_detail_context)


@router.post("/schemas/{schema_id}/sync", dependencies=[IsAuthenticated])
async def sync_schema_api(
    schema: CreatedSchemaDep, syncers: SyncersDep, background_tasks: BackgroundTasks
) -> JSONResponse:
    """Start a background sync for a specific schema by its ID."""
    background_tasks.add_task(run_schema_sync, schema, *syncers)
    return JSONResponse(content={"status": "sync started"})


@router.post("/schemas/{schema_id}/delete", dependencies=[IsAuthenticated])
async def schema_delete_api(
    inventory_api: InventoryAPI, schema: CreatedSchemaDep
) -> JSONResponse:
    """Delete a specific schema from the inventory system by its ID."""
    await inventory_api.delete(f"/schemas/{schema.id}")
    return JSONResponse(content={"status": f"deleted schema: {schema.id}"})


@router.post("/tables/{table_id}/delete", dependencies=[IsAuthenticated])
async def table_delete_api(
    inventory_api: InventoryAPI, table: CreatedTableDep
) -> JSONResponse:
    """Delete a specific table from the inventory system by its ID."""
    await inventory_api.delete(f"/tables/{table.id}")
    return JSONResponse(content={"status": f"deleted table: {table.id}"})
