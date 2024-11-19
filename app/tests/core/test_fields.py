"""Define tests for the app.core.fields module."""

import pytest

from app.core.fields import (
    remove_duplicates,
    resolve_relative_path,
    URL,
    validate_attribute_is_importable,
    validate_log_level,
    validate_module_is_importable,
)


def test_validate_log_level_invalid_string():
    """Test that an invalid log level string raises a ValueError."""
    with pytest.raises(ValueError, match="Invalid log level: 'notalevel'"):
        validate_log_level("notalevel")


def test_remove_duplicates_no_duplicates():
    """Test that a list without duplicates remains unchanged."""
    input_list = [1, 2, 3, 4, 5]
    expected = [1, 2, 3, 4, 5]
    assert remove_duplicates(input_list) == expected


def test_validate_attribute_is_importable_invalid_format():
    """Test that an invalid format raises a ValueError."""
    input_str = "invalidformat"
    with pytest.raises(ValueError, match="Must follow the format module.class"):
        validate_attribute_is_importable(input_str)


def test_validate_module_is_importable_invalid():
    """Test that an invalid module path raises a ValueError."""
    invalid_module = "nonexistent_module"
    with pytest.raises(ValueError, match=f"No module named {invalid_module}"):
        validate_module_is_importable(invalid_module)


def test_resolve_relative_path_invalid_type():
    """Raise a ValueError when an invalid type is provided for the path."""
    invalid_path = None
    with pytest.raises(ValueError, match="Invalid path type: NoneType"):
        resolve_relative_path(invalid_path)


class MockHandler:
    """Mock handler to simulate Pydantic core schema handler."""

    def __call__(self, core_schema):
        """Return a mock Pydantic core schema for testing."""
        return {"type": "string"}


def test_get_pydantic_json_schema():
    """Test that the __get_pydantic_json_schema__ method returns the correct schema."""
    mock_core_schema = {"type": "string"}
    mock_handler = MockHandler()

    expected_schema = {
        "type": "string",
        "format": "uri",
    }

    result = URL.__get_pydantic_json_schema__(mock_core_schema, mock_handler)

    assert result == expected_schema
