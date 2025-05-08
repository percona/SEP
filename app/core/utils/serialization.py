"""Utilities for serializing data."""

import json
from enum import Enum
from typing import Any

from fastapi.encoders import jsonable_encoder

__all__ = ["json_serializer"]


def json_serializer(data: Any, **kwargs: Any) -> str:
    """Serialize a Python object into a JSON-formatted string.

    This function encodes a given Python object using `jsonable_encoder`
    to ensure it is serializable, then converts it to a JSON string using `json.dumps`.

    :param data: The Python object to be serialized. This can be any JSON-serializable
        data type, such as dictionaries, lists, or primitive data types like
        integers, strings, and booleans.
    :type data: Any
    :param kwargs: Additional keyword arguments to pass to :func:`json.dumps`.
    :type kwargs: Any
    :return: A JSON-formatted string representing the serialized form of the input data.
    :rtype: str
    """
    return json.dumps(jsonable_encoder(data), **kwargs)


def enum_serializer(enum_cls: Enum) -> list[dict[str, Any]]:
    """Convert an Enum class into a list of dictionaries with name-value pairs.

    :param enum_cls: The Enum class to serialize.
    :type enum_cls: Enum
    :return: A list of dictionaries where each dictionary has a single key-value
             pair representing the name and value of an Enum member.
    :rtype: list[dict[str, Any]]
    """
    return [{e.name: e.value} for e in enum_cls]
