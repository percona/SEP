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

"""Define the routes for the Tables resource."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import IsAuthenticatedDep
from app.core.db import ListQuery, make_list_query_dep
from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.inventory.crud import TableManager
from app.inventory.deps import SessionDep, TableDep
from app.inventory.models import Table, TableDetailResponse, TableResponse, TableWrite

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tables", tags=["tables"])

TableListQueryDep = Annotated[ListQuery, Depends(make_list_query_dep(TableManager))]


@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_tables(
    session: SessionDep,
    pagination: PaginationDep,
    list_query: TableListQueryDep,
) -> PaginatedResponse[TableResponse]:
    """List Tables."""
    logger.debug("Listing tables")
    return await TableManager.list_query_paginated(
        session,
        list_query=list_query,
        pagination=pagination,
    )


@router.get("/{table_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_table(session: SessionDep, table_id: int) -> TableDetailResponse:
    """Retrieve Table."""
    logger.debug("Retrieving table %s", table_id)
    return await TableManager.get_or_404(
        session,
        select_related=[Table.database],
        id=table_id,
    )


@router.put("/{table_id}", dependencies=[IsAuthenticatedDep])
async def update_table(
    session: SessionDep,
    existing_table: TableDep,
    updated_table: TableWrite,
) -> Table:
    """Update Table."""
    logger.debug("Updating table %s", existing_table.id)
    return await TableManager.update(session, existing_table, updated_table)


@router.delete(
    "/{table_id}",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_table(session: SessionDep, table: TableDep) -> None:
    """Delete Table."""
    logger.debug("Deleting table %s", table.id)
    await TableManager.delete(session, table)
