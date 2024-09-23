"""Define dependencies for the Tasks API."""

from typing import Annotated
from typing import AsyncGenerator

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.db import get_async_session


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
