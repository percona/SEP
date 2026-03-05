# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Utilities for serializing data."""

__all__ = ["json_serializer"]

import json
from typing import Any

from fastapi.encoders import jsonable_encoder


def json_serializer(
    data: Any, encoders_kwargs: dict[str, Any] | None = None, **kwargs: Any
) -> str:
    """Serialize a Python object into a JSON-formatted string.

    This function encodes a given Python object using `jsonable_encoder`
    to ensure it is serializable, then converts it to a JSON string using `json.dumps`.

    :param data: The Python object to be serialized. This can be any JSON-serializable
        data type, such as dictionaries, lists, or primitive data types like
        integers, strings, and booleans.
    :type data: Any
    :param encoders_kwargs: Optional keyword arguments to pass to `jsonable_encoder`.
    :type encoders_kwargs: dict[str, Any] | None
    :param kwargs: Additional keyword arguments to pass to :func:`json.dumps`.
    :type kwargs: Any
    :return: A JSON-formatted string representing the serialized form of the input data.
    :rtype: str
    """
    encoders_kwargs = encoders_kwargs or {}
    return json.dumps(jsonable_encoder(data, **encoders_kwargs), **kwargs)
