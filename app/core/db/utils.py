"""Define database utilities."""

import json
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession


def json_serializer(data: Any) -> str:
    """Serialize a Python object into a JSON-formatted string.

    This function encodes a given Python object using `jsonable_encoder`
    to ensure it is serializable, then converts it to a JSON string using `json.dumps`.

    Parameters
    ----------
    data : Any
        The Python object to be serialized. This can be any JSON-serializable
        data type, such as dictionaries, lists, or primitive data types like
        integers, strings, and booleans.

    Returns
    -------
    str
        A JSON-formatted string representing the serialized form of the input data.

    Notes
    -----
    SQLAlchemy needs this function to serialize Pydantic models.

    """
    return json.dumps(jsonable_encoder(data))


def get_async_session_from_engine(engine: AsyncEngine) -> AsyncSession:
    """Return a new asynchronous session for database operations.

    This function creates a new SQLAlchemy asynchronous session using the predefined
    engine configuration.

    Returns
    -------
    AsyncSession
        A new asynchronous session instance.

    """
    return sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
