# Copyright (C) 2025 Percona LLC
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

"""Define Pydantic-related utilities."""

from typing import Any, TypeVar

from pydantic import TypeAdapter

__all__ = ["run_pydantic_type_validator"]

V = TypeVar("V")


def run_pydantic_type_validator(validate_class: type[V], obj: Any) -> V:
    """Perform Pydantic validation for the specified type with the specified object.

    This function validates a Python object against a Pydantic type and returns the
    validated object.

    :param: validate_class: The class to use for validation.
    :type validate_class: type[V]
    :param: obj: The Python object to validate.
    :type obj: Any
    :return: The validated object.
    :rtype: V
    """
    return TypeAdapter(validate_class).validate_python(obj)
