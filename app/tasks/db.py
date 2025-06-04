"""Define database initialization and utility functions for the Tasks API."""

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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


engine = create_async_engine(
    tasks_settings.DATABASE.URL,
    echo=False,
    json_serializer=json_serializer,
    json_deserializer=json_deserialize,
)


def get_async_session_maker() -> async_sessionmaker:
    """Return a new asynchronous session maker for database operations.

    This function creates a new SQLAlchemy asynchronous session maker using the
    predefined engine configuration.

    :return: A new asynchronous session maker.
    :rtype: async_sessionmaker
    """
    return get_async_session_maker_from_engine(engine)
