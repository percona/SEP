"""Define database initialization and utility functions for the Inventory API."""

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.utils import get_async_session_from_engine
from app.core.db.utils import json_serializer
from app.inventory.config import inventory_settings

engine = create_async_engine(
    inventory_settings.DATABASE.URL,
    echo=True,
    json_serializer=json_serializer,
)


def get_async_session() -> AsyncSession:
    """Return a new asynchronous session for database operations.

    This function creates a new SQLAlchemy asynchronous session using the predefined
    engine configuration.

    Returns
    -------
    AsyncSession
        A new asynchronous session instance.

    """
    return get_async_session_from_engine(engine)
