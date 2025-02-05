"""Define the routes for the Tables resource."""

import logging

from fastapi import APIRouter, status

from app.api.deps import IsAuthenticatedDep
from app.core.utils.fields import RequiredStr
from app.inventory.crud import TableManager
from app.inventory.deps import SessionDep, TableDep
from app.inventory.models import Table, TableDetailResponse, TableResponse, TableWrite

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tables", tags=["tables"])


@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_tables(session: SessionDep) -> list[TableResponse]:
    """List Tables."""
    logger.debug("Listing tables")
    return await TableManager.list(session)


@router.get("/id", dependencies=[IsAuthenticatedDep])
async def get_table_id(
    session: SessionDep,
    name: RequiredStr,
    schema_id: int,
) -> dict:
    """Retrieve a Table's ID by its unique name and schema_id."""
    logger.debug("Retrieving table id for name=%s, schema_id=%s", name, schema_id)
    table = await TableManager.get_or_404(session, name=name, schema_id=schema_id)
    return {"table_id": table.id}


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
