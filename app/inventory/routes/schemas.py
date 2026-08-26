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

"""Define the routes for the Schemas resource."""

import logging
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import IsAuthenticatedDep
from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.inventory.crud import (
    RetiredInclusiveSchemaManager,
    RetiredInclusiveTableManager,
    SchemaManager,
    TableManager,
)
from app.inventory.deps import (
    RetirableSchemaDep,
    SchemaDep,
    SchemaListQueryDep,
    SessionDep,
    TableListQueryDep,
)
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
async def list_schemas(
    session: SessionDep,
    pagination: PaginationDep,
    list_query: SchemaListQueryDep,
    *,
    include_retired: Annotated[bool, Query()] = False,
) -> PaginatedResponse[SchemaResponse]:
    """List Schemas."""
    logger.debug("Listing schemas")
    manager = RetiredInclusiveSchemaManager if include_retired else SchemaManager
    return await manager.list_query_paginated(
        session,
        list_query=list_query,
        select_related=[Schema.tables],
        pagination=pagination,
    )


@router.get("/{schema_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_schema(
    session: SessionDep,
    schema_id: int,
    *,
    include_retired: Annotated[bool, Query()] = False,
) -> SchemaDetailResponse:
    """Retrieve Schema."""
    logger.debug("Retrieving schema %s", schema_id)
    manager = RetiredInclusiveSchemaManager if include_retired else SchemaManager
    return await manager.get_or_404(
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
async def retire_schema(session: SessionDep, schema: RetirableSchemaDep) -> None:
    """Retire Schema and its tables, keeping the rows resolvable.

    :param session: The asynchronous database session.
    :param schema: The schema to retire, retired or not.
    """
    logger.debug("Retiring schema %s", schema.id)
    await SchemaManager.retire(session, schema)


@router.post(
    "/{schema_id}/revive",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revive_schema(session: SessionDep, schema: RetirableSchemaDep) -> None:
    """Revive a retired Schema together with its retired ancestors.

    :param session: The asynchronous database session.
    :param schema: The schema to revive, retired or not.
    :raises HTTPConflictException: If an active entity already holds the unique
        key the revived schema would reclaim.
    """
    logger.debug("Reviving schema %s", schema.id)
    await SchemaManager.revive(session, schema)


@router.get("/{schema_id}/tables/", dependencies=[IsAuthenticatedDep])
async def list_tables_by_schema(
    session: SessionDep,
    schema: SchemaDep,
    pagination: PaginationDep,
    list_query: TableListQueryDep,
    *,
    include_retired: Annotated[bool, Query()] = False,
) -> PaginatedResponse[TableResponse]:
    """List Tables by Schema."""
    logger.debug("Listing tables for schema '%s'", schema.id)
    manager = RetiredInclusiveTableManager if include_retired else TableManager
    return await manager.list_query_paginated(
        session,
        list_query=list_query,
        pagination=pagination,
        schema_id=schema.id,
    )


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
