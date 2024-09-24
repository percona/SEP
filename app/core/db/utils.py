"""Define database utilities."""

import json
from typing import Any

from fastapi.encoders import jsonable_encoder


def json_serializer(data: Any) -> str:
    """Serializes a Python object into a JSON-formatted string.

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
