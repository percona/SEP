"""Define database initialization and utility functions for the Inventory API."""

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.inventory.config import inventory_settings

engine = create_async_engine(
    inventory_settings.DATABASE.URL,
    echo=False,
    json_serializer=json_serializer,
)


def get_async_session_maker() -> sessionmaker:
    """Return a new asynchronous session maker for database operations.

    This function creates a new SQLAlchemy asynchronous session maker using the
    predefined engine configuration.

    :return: A new asynchronous session maker.
    :rtype: sessionmaker
    """
    return get_async_session_maker_from_engine(engine)
