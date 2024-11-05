"""Define core models for all apps."""

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.utils import deep_lowercase_dict_keys, to_uppercase


class BaseCaseInsensitiveModel(BaseModel):
    """A base model with case-insensitive alias generation.

    This model uses a custom alias generator that converts field names to uppercase.
    It also allows population of fields by their name, making it case-insensitive
    when handling data.
    """

    model_config = ConfigDict(alias_generator=to_uppercase, populate_by_name=True)


class BaseLowercaseModel(BaseCaseInsensitiveModel):
    """Define a base model that ensures all dictionary keys are lowercase.

    Inherits from `BaseCaseInsensitiveModel` and applies a transformation to convert
    all string keys in input data to lowercase before validation.
    """

    @model_validator(mode="before")
    @classmethod
    def force_lowercase_fields(cls, data: Any) -> Any:
        """Convert all string keys in input data to lowercase before validation.

        :param data: The input data to be validated, typically a dictionary.
        :type data: Any
        :return: The transformed data with all string keys in lowercase.
        :rtype: Any
        """
        if isinstance(data, dict):
            data = deep_lowercase_dict_keys(data)
        return data
