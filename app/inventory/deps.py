"""Define dependencies for the Inventory API."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.inventory.crud import NodeManager
from app.inventory.crud import SchemaManager
from app.inventory.crud import ServiceManager
from app.inventory.crud import TableManager
from app.inventory.db import get_async_session
from app.inventory.models import Node
from app.inventory.models import Schema
from app.inventory.models import Service
from app.inventory.models import Table


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an asynchronous database session for FastAPI routes.

    This function provides a dependency for FastAPI routes that yields an `AsyncSession`
    for interacting with the database. The session is properly closed after use.

    Yields
    ------
    AsyncGenerator[AsyncSession, None]
        An asynchronous session for database operations.

    """
    async_session = get_async_session()
    async with async_session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_node(session: SessionDep, node_id: int) -> Node:
    """Retrieve a node by its unique identifier.

    Fetch the node corresponding to the provided `node_id`. If no such node exists,
    raise an HTTP 404 Not Found exception.

    Parameters
    ----------
    session : AsyncSession
        The asynchronous database session.
    node_id : int
        The unique identifier of the node to retrieve.

    Returns
    -------
    Node
        The node instance corresponding to the provided `node_id`.

    Raises
    ------
    HTTPNotFoundException
        If no node with the specified `node_id` exists.

    """
    return await NodeManager.get_or_404(session, id=node_id)


async def get_service(session: SessionDep, service_id: int) -> Service:
    """Retrieve a service by its unique identifier.

    Fetch the service corresponding to the provided `service_id`.
    If no such service exists, raise an HTTP 404 Not Found exception.

    Parameters
    ----------
    session : AsyncSession
        The asynchronous database session.
    service_id : int
        The unique identifier of the service to retrieve.

    Returns
    -------
    Service
        The service instance corresponding to the provided `service_id`.

    Raises
    ------
    HTTPNotFoundException
        If no service with the specified `service_id` exists.

    """
    return await ServiceManager.get_or_404(session, id=service_id)


async def get_schema(session: SessionDep, schema_id: int) -> Schema:
    """Retrieve a schema by its unique identifier.

    Fetch the schema corresponding to the provided `schema_id`.
    If no such schema exists, raise an HTTP 404 Not Found exception.

    Parameters
    ----------
    session : AsyncSession
        The asynchronous database session.
    schema_id : int
        The unique identifier of the schema to retrieve.

    Returns
    -------
    Schema
        The schema instance corresponding to the provided `schema_id`.

    Raises
    ------
    HTTPNotFoundException
        If no schema with the specified `schema_id` exists.

    """
    return await SchemaManager.get_or_404(session, id=schema_id)


async def get_table(session: SessionDep, table_id: int) -> Table:
    """Retrieve a table by its unique identifier.

    Fetch the table corresponding to the provided `table_id`. If no such table exists,
    raise an HTTP 404 Not Found exception.

    Parameters
    ----------
    session : AsyncSession
        The asynchronous database session.
    table_id : int
        The unique identifier of the table to retrieve.

    Returns
    -------
    Table
        The table instance corresponding to the provided `table_id`.

    Raises
    ------
    HTTPNotFoundException
        If no table with the specified `table_id` exists.

    """
    return await TableManager.get_or_404(session, id=table_id)


NodeDep = Annotated[Node, Depends(get_node)]
ServiceDep = Annotated[Node, Depends(get_service)]
SchemaDep = Annotated[Node, Depends(get_schema)]
TableDep = Annotated[Node, Depends(get_table)]
