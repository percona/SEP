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

from fastapi import APIRouter, Depends, status

from app.api.deps import IsAuthenticatedDep
from app.core.db import ListQuery, make_list_query_dep
from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
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

SchemaListQueryDep = Annotated[ListQuery, Depends(make_list_query_dep(SchemaManager))]
TableListQueryDep = Annotated[ListQuery, Depends(make_list_query_dep(TableManager))]


@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_schemas(
    session: SessionDep,
    pagination: PaginationDep,
    list_query: SchemaListQueryDep,
) -> PaginatedResponse[SchemaResponse]:
    """List Schemas."""
    logger.debug("Listing schemas")
    return await SchemaManager.list_query_paginated(
        session,
        list_query=list_query,
        select_related=[Schema.tables],
        pagination=pagination,
    )


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
    pagination: PaginationDep,
    list_query: TableListQueryDep,
) -> PaginatedResponse[TableResponse]:
    """List Tables by Schema."""
    logger.debug("Listing tables for schema '%s'", schema.id)
    return await TableManager.list_query_paginated(
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
