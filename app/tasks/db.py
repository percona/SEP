"""Define database initialization and utility functions for the Tasks API."""

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.tasks.config import tasks_settings
from app.tasks.models import TaskExecutionRequest, TaskExecutionResult


def json_deserialize(raw_data: str) -> Any:
    """Deserialize a JSON string into a Python object.

    This function attempts to parse the given JSON string into one of the following models
    (in order): TaskExecutionRequest or TaskExecutionResult. If the JSON does not match
    either model, the parsed JSON dictionary is returned as-is.

    :param raw_data: The JSON string to deserialize.
    :type raw_data: str
    :return: A TaskExecutionRequest or TaskExecutionResult object if deserialization
             succeeds, otherwise the parsed JSON data as a dictionary.
    :rtype: Any
    """
    data = json.loads(raw_data)
    for model in (TaskExecutionRequest, TaskExecutionResult):
        try:
            return model(**data)
        except ValidationError:
            continue
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
