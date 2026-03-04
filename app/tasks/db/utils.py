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

"""Define database utility functions for the Tasks API."""

import json
from typing import Any

from pydantic import ValidationError

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
