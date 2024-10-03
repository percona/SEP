"""Define the routes for the Schemas resource."""

import logging

from fastapi import APIRouter

from app.api.deps import IsAuthenticatedDep
from app.inventory.crud import SchemaManager
from app.inventory.crud import TableManager
from app.inventory.deps import SchemaDep
from app.inventory.deps import SessionDep
from app.inventory.models import Schema
from app.inventory.models import SchemaResponse
from app.inventory.models import SchemaWrite
from app.inventory.models import Table
from app.inventory.models import TableResponse
from app.inventory.models import TableWrite

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_schemas(session: SessionDep) -> list[SchemaResponse]:
    """List Schemas."""
    logger.debug("Listing schemas")
    return await SchemaManager.list(session, select_related=[Schema.tables])


@router.get("/{schema_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_schema(session: SessionDep, schema_id: int) -> SchemaResponse:
    """Retrieve Schema."""
    logger.debug("Retrieving schema %s", schema_id)
    return await SchemaManager.get_or_404(
        session,
        select_related=[Schema.tables],
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


@router.delete("/{schema_id}", dependencies=[IsAuthenticatedDep])
async def delete_schema(session: SessionDep, schema: SchemaDep) -> SchemaResponse:
    """Delete Schema."""
    logger.debug("Deleting schema %s", schema.id)
    return await SchemaManager.delete(session, schema)


@router.get("/{schema_id}/tables/", dependencies=[IsAuthenticatedDep])
async def list_tables_by_schema(
    session: SessionDep,
    schema: SchemaDep,
) -> list[TableResponse]:
    """List Tables by Schema."""
    logger.debug("Listing tables for schema '%s'", schema.id)
    return await TableManager.list(session, schema_id=schema.id)


@router.post("/{schema_id}/tables/", dependencies=[IsAuthenticatedDep])
async def create_table_for_schema(
    session: SessionDep,
    schema: SchemaDep,
    table: TableWrite,
) -> Table:
    """Create Table for Schema."""
    logger.debug("Creating table for schema %s: %s", schema.id, table)
    return await TableManager.create(session, table, schema_id=schema.id)
