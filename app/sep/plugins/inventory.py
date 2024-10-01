"""Define routes for the Inventory Plugin."""

import logging
from typing import Annotated

from fastapi import APIRouter
from fastapi import Form
from fastapi import Request
from fastapi import status
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from app.sep.config import sep_settings
from app.sep.deps import DefaultContext
from app.sep.deps import InventoryAPI
from app.sep.deps import IsAuthenticated
from app.sep.inventory import Node
from app.sep.inventory import Schema
from app.sep.inventory import Service
from app.sep.inventory import Table

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def node_list(
    request: Request,
    context: DefaultContext,
    inventory_api: InventoryAPI,
) -> HTMLResponse:
    """List Nodes."""
    context["inventory"] = await inventory_api.get("/")
    return templates.TemplateResponse(
        request=request,
        name="inventory/node-list.html",
        context=context,
    )


@router.get("/{node_id}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def node_detail(
    request: Request,
    node_id: int,
    context: DefaultContext,
    inventory_api: InventoryAPI,
) -> HTMLResponse:
    """Retrieve Node Details."""
    node = await inventory_api.get(f"/{node_id}")
    context["node"] = node
    return templates.TemplateResponse(
        request=request,
        name="inventory/node-detail.html",
        context=context,
    )


# TODO: Use pydantic models instead of retyping each argument
@router.post("/", dependencies=[IsAuthenticated])
async def node_create(
    inventory_api: InventoryAPI,
    node_data: Annotated[Node, Form()],
) -> RedirectResponse:
    """Create Node."""
    await inventory_api.post("/", json=node_data.model_dump())
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
    request: Request,
    service_id: int,
    context: DefaultContext,
    inventory_api: InventoryAPI,
) -> HTMLResponse:
    """Retrieve Service Details."""
    service = await inventory_api.get(f"/services/{service_id}")
    context["service"] = service
    return templates.TemplateResponse(
        request=request,
        name="inventory/service-detail.html",
        context=context,
    )


# TODO: Use pydantic models instead of retyping each argument


@router.post("/{node_id}/services/", dependencies=[IsAuthenticated])
async def service_create_for_node(
    node_id: int,
    inventory_api: InventoryAPI,
    service_data: Annotated[Service, Form()],
) -> RedirectResponse:
    """Create Service for Node."""
    await inventory_api.post(
        f"/{node_id}/services/",
        json=service_data.model_dump(),
    )
    return RedirectResponse(
        f"/inventory/{node_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/services/{service_id}/delete", dependencies=[IsAuthenticated])
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
    request: Request,
    schema_id: int,
    context: DefaultContext,
    inventory_api: InventoryAPI,
) -> HTMLResponse:
    """Retrieve Schema Details."""
    schema = await inventory_api.get(f"/schemas/{schema_id}")
    context["schema"] = schema
    return templates.TemplateResponse(
        request=request,
        name="inventory/schema-detail.html",
        context=context,
    )


# TODO: Use pydantic models instead of retyping each argument


@router.post("/services/{service_id}/schemas/", dependencies=[IsAuthenticated])
async def schema_create_for_service(
    service_id: int,
    inventory_api: InventoryAPI,
    schema_data: Annotated[Schema, Form()],
) -> RedirectResponse:
    """Create Schema for Service."""
    await inventory_api.post(
        f"/services/{service_id}/schemas/",
        json=schema_data.model_dump(),
    )
    return RedirectResponse(
        f"/inventory/services/{service_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/schemas/{schema_id}/delete", dependencies=[IsAuthenticated])
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


@router.post("/schemas/{schema_id}/tables/", dependencies=[IsAuthenticated])
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


@router.post("/tables/{table_id}/delete", dependencies=[IsAuthenticated])
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
