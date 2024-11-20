"""Define tests for the app.core.models module."""

import pytest
from pydantic import ValidationError

from app.core.models import BaseLowercaseModel

TEST_INT_VALUE = 42
TEST_STRING_VALUE = "value1"


# Example model extending BaseLowercaseModel for testing
class ExampleModel(BaseLowercaseModel):
    """Demonstrate behavior of BaseLowercaseModel with example fields."""

    field_one: str
    field_two: int


def test_case_insensitive_alias_generation():
    """Test that the model accepts uppercase keys as input."""
    data = {"FIELD_ONE": TEST_STRING_VALUE, "FIELD_TWO": TEST_INT_VALUE}
    model = ExampleModel(**data)
    assert model.field_one == TEST_STRING_VALUE
    assert model.field_two == TEST_INT_VALUE


def test_lowercase_key_transformation():
    """Test that keys in the input dictionary are transformed to lowercase."""
    data = {"FiElD_OnE": TEST_STRING_VALUE, "FiElD_Two": TEST_INT_VALUE}
    model = ExampleModel(**data)
    assert model.field_one == TEST_STRING_VALUE
    assert model.field_two == TEST_INT_VALUE

    with pytest.raises(ValidationError):
        ExampleModel(FIELD_ONE="missing_field", FIELD_THREE=50)


def test_non_dict_input_returns_data_as_is():
    """Test that non-dict input to transform_fields is returned unchanged."""
    non_dict_input = ["list", "of", "values"]
    transformed = ExampleModel.transform_fields(non_dict_input)
    assert transformed == non_dict_input
