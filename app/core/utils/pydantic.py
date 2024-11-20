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
