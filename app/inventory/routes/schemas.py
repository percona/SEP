"""Define the routes for the Schemas resource."""

import logging

from fastapi import APIRouter, status

from app.api.deps import IsAuthenticatedDep
from app.core.utils.fields import RequiredStr
from app.inventory.crud import SchemaManager, TableManager
from app.inventory.deps import SchemaDep, SessionDep
from app.inventory.models import (
    Schema,
    SchemaDetailResponse,
    SchemaResponse,
    SchemaWrite,
    Table,
    TableResponse,
    TableWrite,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schemas", tags=["schemas"])


@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_schemas(session: SessionDep) -> list[SchemaResponse]:
    """List Schemas."""
    logger.debug("Listing schemas")
    return await SchemaManager.list(session, select_related=[Schema.tables])


@router.get("/id", dependencies=[IsAuthenticatedDep])
async def get_schema_id(
    session: SessionDep,
    name: RequiredStr,
    service_id: int,
) -> dict:
    """Retrieve a Schema's ID by its unique name and service_id."""
    logger.debug("Retrieving schema id for name=%s, service_id=%s", name, service_id)
    schema = await SchemaManager.get_or_404(session, name=name, service_id=service_id)
    return {"schema_id": schema.id}


@router.get("/{schema_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_schema(session: SessionDep, schema_id: int) -> SchemaDetailResponse:
    """Retrieve Schema."""
    logger.debug("Retrieving schema %s", schema_id)
    return await SchemaManager.get_or_404(
        session,
        select_related=[Schema.tables, Schema.service],
        id=schema_id,
    )


@router.put("/{schema_id}", dependencies=[IsAuthenticatedDep])
async def update_schema(
    session: SessionDep,
    existing_schema: SchemaDep,
    updated_schema: SchemaWrite,
) -> Schema:
    """Update Schema."""
    logger.debug("Updating schema %s", existing_schema.id)
    return await SchemaManager.update(session, existing_schema, updated_schema)


@router.delete(
    "/{schema_id}",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_schema(session: SessionDep, schema: SchemaDep) -> None:
    """Delete Schema."""
    logger.debug("Deleting schema %s", schema.id)
    await SchemaManager.delete(session, schema)


@router.get("/{schema_id}/tables/", dependencies=[IsAuthenticatedDep])
async def list_tables_by_schema(
    session: SessionDep,
    schema: SchemaDep,
) -> list[TableResponse]:
    """List Tables by Schema."""
    logger.debug("Listing tables for schema '%s'", schema.id)
    return await TableManager.list(session, schema_id=schema.id)


@router.post(
    "/{schema_id}/tables/",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_201_CREATED,
)
async def create_table_for_schema(
    session: SessionDep,
    schema: SchemaDep,
    table: TableWrite,
) -> Table:
    """Create Table for Schema."""
    logger.debug("Creating table for schema %s: %s", schema.id, table)
    return await TableManager.create(session, table, schema_id=schema.id)
