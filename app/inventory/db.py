"""Define database initialization and utility functions for the Inventory API."""

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine, create_async_engine

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.inventory.config import inventory_settings


def get_async_engine() -> AsyncEngine:
    """Create and return SQLAlchemy AsyncEngine for the Inventory database.

    :return: The SQLAlchemy AsyncEngine for the Inventory database.
    :rtype: AsyncEngine
    """
    return create_async_engine(
        inventory_settings.DATABASE.URL,
        echo=False,
        json_serializer=json_serializer,
    )


engine = get_async_engine()


def get_async_session_maker(*, create_new_engine: bool = False) -> async_sessionmaker:
    """Return a new asynchronous session maker for database operations.

    This function creates a new SQLAlchemy asynchronous session maker using the
    predefined engine configuration.

    :param create_new_engine: A flag to indicate whether to create a new async engine
        with `get_async_engine()` instead of using the already created `engine`.
        Defaults to False.
    :type create_new_engine: bool
    :return: A new asynchronous session maker.
    :rtype: async_sessionmaker
    """
    if create_new_engine:
        return get_async_session_maker_from_engine(get_async_engine())
    return get_async_session_maker_from_engine(engine)
