"""Define tests for the app.core.utils module."""

import sys
from base64 import b64encode
from datetime import UTC
from http import HTTPStatus
from importlib import util

import pytest

from app.core.utils import (
    async_run,
    b64encode_str,
    ErrorFormatter,
    import_var,
    json_serializer,
    minify_file_content,
    slugify,
    sort_dict,
)


class TestErrorFormatter:
    """Tests for the ErrorFormatter class."""

    def setup_method(self):
        """Set up an instance of ErrorFormatter for testing."""
        self.formatter = ErrorFormatter()

    def test_format_error_heading_valid_status(self):
        """Test formatting of error heading for a valid HTTP status code."""
        details = {"status_code": 404}
        heading = self.formatter.format_error_heading(details)
        assert heading == HTTPStatus.NOT_FOUND.phrase

    def test_format_error_heading_invalid_status(self):
        """Test formatting of error heading for an invalid HTTP status code."""
        details = {"status_code": 999}
        heading = self.formatter.format_error_heading(details)
        assert heading == HTTPStatus.NOT_FOUND.phrase

    def test_format_error_message_valid_status(self):
        """Test formatting of error message for a valid HTTP status code."""
        details = {"status_code": 400}
        message = self.formatter.format_error_message(details)
        assert message == HTTPStatus.BAD_REQUEST.description

    def test_format_error_message_invalid_status(self):
        """Test formatting of error message for an invalid HTTP status code."""
        details = {"status_code": 123}
        message = self.formatter.format_error_message(details)
        assert message == HTTPStatus.NOT_FOUND.description

    def test_details_property_getter_setter(self):
        """Test getting and setting of details property."""
        details = {"key": "value"}
        self.formatter.details = details
        assert self.formatter.details == details

    def test_details_setter_type_error(self):
        """Test that setting non-dict to details raises a TypeError."""
        with pytest.raises(TypeError):
            self.formatter.details = "not a dict"


def sample_func(x, y):
    """Sample function that returns the sum of two numbers."""
    return x + y


def long_running_func():
    """Sample function that simulates a long-running task."""
    import time

    time.sleep(1)
    return "done"


def error_func():
    """Sample function that raises a ValueError."""
    raise ValueError("Test error")


@pytest.mark.asyncio
async def test_async_run():
    """Test async_run utility with different function scenarios."""
    result = await async_run(sample_func, 2, 3)
    expected_result = 5
    assert result[0] == expected_result

    result = await async_run(long_running_func)
    assert result[0] == "done"

    with pytest.raises(ValueError, match="Test error"):
        await async_run(error_func)


def test_slugify():
    """Test slugify utility for various input cases."""
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("  Python@3.8  ") == "python-3-8"
    assert slugify("Café Münchén") == "cafe-munchen"
    assert slugify("___") == ""
    assert slugify("") == ""
    assert slugify("No_Special-Characters") == "no-special-characters"


def test_import_var():
    """Test import_var utility for dynamic imports."""
    module_name = "temp_module"
    spec = util.spec_from_loader(module_name, loader=None)
    temp_module = util.module_from_spec(spec)
    sys.modules[module_name] = temp_module
    temp_module.test_var = 42
    expected_value = 42

    assert import_var("temp_module.test_var") == expected_value

    with pytest.raises(AttributeError):
        import_var("temp_module.non_existent_var")

    with pytest.raises(ModuleNotFoundError):
        import_var("nonexistent_module.var")


def test_b64encode_str():
    """Test b64encode_str utility for base64 encoding strings."""
    assert b64encode_str("hello") == "aGVsbG8="
    assert b64encode_str("") == ""

    encoded = b64encode_str("café", encoding="latin-1")
    assert encoded == b64encode("café".encode("latin-1")).decode("latin-1")


def test_sort_dict():
    """Test sort_dict utility for sorting dictionaries."""
    unsorted_dict = {"banana": 3, "apple": 4, "cherry": 2}
    sorted_by_key = sort_dict(unsorted_dict, key=lambda item: item[0])
    assert list(sorted_by_key.keys()) == ["apple", "banana", "cherry"]

    sorted_by_value = sort_dict(unsorted_dict, key=lambda item: item[1])
    assert list(sorted_by_value.keys()) == ["cherry", "banana", "apple"]

    assert sort_dict({}, key=lambda item: item[0]) == {}

    unsorted_dict = {3: "three", 1: "one", 2: "two"}
    sorted_dict = sort_dict(unsorted_dict, key=lambda item: item[0])
    assert list(sorted_dict.keys()) == [1, 2, 3]


def test_json_serializer():
    """Test json_serializer utility for converting data to JSON strings."""
    data = {"name": "Alice", "age": 30, "is_active": True}
    json_str = json_serializer(data)
    assert json_str == '{"name": "Alice", "age": 30, "is_active": true}'

    data = {
        "users": [
            {"id": 1, "name": "Bob"},
            {"id": 2, "name": "Charlie"},
        ],
        "count": 2,
    }
    json_str = json_serializer(data)
    assert (
        json_str
        == '{"users": [{"id": 1, "name": "Bob"}, {"id": 2, "name": "Charlie"}], "count": 2}'
    )

    from datetime import datetime

    data = {"timestamp": datetime(2024, 1, 1, tzinfo=UTC)}
    json_str = json_serializer(data)
    assert json_str == '{"timestamp": "2024-01-01T00:00:00+00:00"}'

    class Custom:
        """Custom class for testing JSON serialization."""

        def __init__(self, value):
            self.value = value

    data = {"custom": Custom(10)}
    json_str = json_serializer(data)
    assert json_str == '{"custom": {"value": 10}}'


def test_minify_valid_python_code():
    """Test minification of valid Python code."""
    python_code = """
def foo():
    x = 1
    y = 2
    return x + y
"""
    minified_code = minify_file_content(python_code, file_ext="py")
    assert minified_code.strip() != ""
    assert "\n" not in minified_code or len(minified_code.split("\n")) == 1
    assert "def" in minified_code
    assert "return" in minified_code


def test_minify_unrelated_file_extension():
    """Test minification with a non-Python file extension."""
    text_content = "This is some plain text."
    result = minify_file_content(text_content, file_ext="txt")
    assert result == text_content


def test_minify_with_syntax_error():
    """Test that syntax errors are handled gracefully."""
    broken_python_code = "def baz()\n    print('missing colon')"
    result = minify_file_content(broken_python_code, file_ext="py")
    assert result == broken_python_code
