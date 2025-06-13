"""Define Pydantic-related utilities."""

from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter

__all__ = ["run_pydantic_type_validator"]

V = TypeVar("V")
T = TypeVar("T", bound=BaseModel)


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