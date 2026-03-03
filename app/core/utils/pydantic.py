# Copyright 2025 Percona LLC
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

__all__ = [
    "CustomFieldMetadata",
    "extract_model_from_instance",
    "loc_to_dot_sep",
    "run_pydantic_type_validator",
]

from collections.abc import Hashable
from contextlib import suppress
from typing import Any, NamedTuple, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic.fields import Field, FieldInfo

V = TypeVar("V")
T = TypeVar("T", bound=BaseModel)


class CustomFieldMetadata(NamedTuple):
    """Represent custom metadata for a Pydantic field.

    :param key: The key of the metadata.
    :type key: Hashable
    :param value: The value of the metadata.
    :type value: Any
    """

    key: Hashable
    value: Any

    @classmethod
    def from_dict(cls, data: dict[Any, Any]) -> list["CustomFieldMetadata"]:
        """Create a list of CustomFieldMetadata instances from a dictionary.

        :param data: A dictionary containing key-value pairs to be converted into
            CustomFieldMetadata instances.
        :type data: dict[Any, Any]
        :return: A list of CustomFieldMetadata instances.
        :rtype: list[CustomFieldMetadata]
        """
        return [cls(key=key, value=value) for key, value in data.items()]

    @classmethod
    def from_field(
        cls, field: FieldInfo, *, strict: bool = False
    ) -> list["CustomFieldMetadata"]:
        """Extract custom metadata from a Pydantic field.

        :param field: The Pydantic field from which to extract metadata.
        :type field: FieldInfo
        :param strict: Whether to perform strict type checking. If `True`, only items
            that are instances of the class will be returned. If `False`, items that can
            be coerced to the class will also be included. Defaults to `False`.
        :type strict: bool
        """
        if strict:
            return [item for item in field.metadata if isinstance(item, cls)]
        metadata = []
        for item in field.metadata:
            with suppress(ValidationError):
                metadata.append(run_pydantic_type_validator(cls, item))
        return metadata

    @classmethod
    def field_to_dict(cls, field: FieldInfo, *, strict: bool = False) -> dict[Any, Any]:
        """Convert the custom metadata of a Pydantic field to a dictionary.

        :param field: The Pydantic field from which to extract metadata.
        :type field: FieldInfo
        :param strict: Whether to perform strict type checking. If `True`, only items
            that are instances of the class will be returned. If `False`, items that can
            be coerced to the class will also be included. Defaults to `False`.
        :type strict: bool
        :return: A dictionary containing the key-value pairs from the metadata.
        :rtype: dict[Any, Any]
        """
        return cls.to_dict(*cls.from_field(field, strict=strict))

    @staticmethod
    def to_dict(*metadata: "CustomFieldMetadata") -> dict[Any, Any]:
        """Convert a list of CustomFieldMetadata instances to a dictionary.

        :param metadata: A variable number of CustomFieldMetadata instances.
        :type metadata: CustomFieldMetadata
        :return: A dictionary containing the key-value pairs from the metadata
            instances.
        :rtype: dict[Any, Any]
        """
        return {meta.key: meta.value for meta in metadata}


def field_with_metadata(
    *args: Any, metadata: dict[Any, Any] | None = None, **kwargs: Any
) -> FieldInfo:
    """Create a Pydantic Field with custom metadata.

    :param args: Positional arguments to pass to the Field constructor.
    :type args: Any
    :param metadata: A dictionary containing key-value pairs to be added as custom
        metadata to the field. Defaults to `None`.
    :type metadata: dict[Any, Any] | None
    :param kwargs: Keyword arguments to pass to the Field constructor.
    :type kwargs: Any
    :return: A Pydantic Field with the specified metadata.
    :rtype: FieldInfo
    """
    field = Field(*args, **kwargs)
    field.metadata.extend(CustomFieldMetadata.from_dict(metadata or {}))
    return field


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


def extract_model_from_instance(instance: BaseModel, model_cls: type[T]) -> T:
    """Extract and validate only matching fields from one Pydantic model to another.

    This function filters the source model's data to match only the fields defined
    in the target model class, then performs validation using Pydantic.

    :param instance: The source Pydantic model instance.
    :type instance: BaseModel
    :param model_cls: The target model class to validate against.
    :type model_cls: Type[T]
    :return: An instance of the target model with validated and filtered data.
    :rtype: T
    """
    data = instance.model_dump()
    allowed_keys = model_cls.model_fields.keys()
    filtered_data = {k: data[k] for k in allowed_keys if k in data}
    return TypeAdapter(model_cls).validate_python(filtered_data)


def loc_to_dot_sep(loc: tuple[str | int, ...]) -> str:
    """Convert a Pydantic error location tuple to a dot-separated string.

    This function transforms a tuple representing the location of an error in a
    Pydantic model into a human-readable dot-separated string format.

    :param loc: A tuple representing the location of an error in a Pydantic model. Each
        element can be either a string (for field names) or an integer (for list
        indices).
    :type loc: tuple[str | int, ...]
    :return: A dot-separated string representing the error location.
    :rtype: str
    :raises TypeError: If an element in the `loc` tuple is neither a string nor an
        integer.
    """
    path = ""
    for loc_part_index, loc_part in enumerate(loc):
        if isinstance(loc_part, str):
            if loc_part_index > 0:
                path += "."
            path += loc_part
        elif isinstance(loc_part, int):
            path += f"[{loc_part}]"
        else:
            raise TypeError("Unexpected type")
    return path
