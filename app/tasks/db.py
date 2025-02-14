"""Define database initialization and utility functions for the Tasks API."""

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine, create_async_engine

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.tasks.config import tasks_settings
from app.tasks.models import TaskExecutionRequest


def json_deserialize(raw_data: str) -> Any:
    """Deserialize a JSON string into a Python object.

    Attempts to deserialize the input string into a `TaskExecutionRequest` model.
    If validation fails, the raw JSON data is returned as a dictionary.

    :param raw_data: The JSON string to deserialize.
    :type raw_data: str
    :return: A `TaskExecutionRequest` object if deserialization is successful,
        otherwise the raw data.
    :rtype: Any
    """
    data = json.loads(raw_data)
    try:
        return TaskExecutionRequest(**data)
    except ValidationError:
        return data


def get_async_engine() -> AsyncEngine:
    """Create and return SQLAlchemy AsyncEngine for the Tasks database.

    :return: The SQLAlchemy AsyncEngine for the Tasks database.
    :rtype: AsyncEngine
    """
    return create_async_engine(
        tasks_settings.DATABASE.URL,
        echo=False,
        json_serializer=json_serializer,
        json_deserializer=json_deserialize,
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
