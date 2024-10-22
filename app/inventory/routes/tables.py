"""Define the routes for the Tables resource."""

import logging

from fastapi import APIRouter

from app.api.deps import IsAuthenticatedDep
from app.inventory.crud import TableManager
from app.inventory.deps import SessionDep, TableDep
from app.inventory.models import Table, TableDetailResponse, TableResponse, TableWrite

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_tables(session: SessionDep) -> list[TableResponse]:
    """List Tables."""
    logger.debug("Listing tables")
    return await TableManager.list(session)


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


@router.delete("/{table_id}", dependencies=[IsAuthenticatedDep])
async def delete_table(session: SessionDep, table: TableDep) -> TableResponse:
    """Delete Table."""
    logger.debug("Deleting table %s", table.id)
    return await TableManager.delete(session, table)
