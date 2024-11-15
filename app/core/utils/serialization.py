"""Utilities for serializing data."""

import json
from typing import Any

from fastapi.encoders import jsonable_encoder

__all__ = ["json_serializer"]


def json_serializer(data: Any) -> str:
    """Serialize a Python object into a JSON-formatted string.

    This function encodes a given Python object using `jsonable_encoder`
    to ensure it is serializable, then converts it to a JSON string using `json.dumps`.

    :param data: The Python object to be serialized. This can be any JSON-serializable
        data type, such as dictionaries, lists, or primitive data types like
        integers, strings, and booleans.
    :type data: Any
    :return: A JSON-formatted string representing the serialized form of the input data.
    :rtype: str
    """
    return json.dumps(jsonable_encoder(data))
