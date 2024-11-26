"""Define tests for the app.core.utils module."""

import sys
from base64 import b64encode
from datetime import datetime, timedelta, timezone, UTC
from importlib import util
from unittest.mock import MagicMock, patch

import pytest

from app.core.utils.asyncio import async_run
from app.core.utils.datetime import make_datetime_utc
from app.core.utils.dict import sort_dict
from app.core.utils.imports import import_var
from app.core.utils.serialization import json_serializer
from app.core.utils.string import b64encode_str, slugify
from app.tasks.execution.utils import minify_file_content


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


def test_make_datetime_utc_with_naive_datetime():
    """Test that a naive datetime is converted to an aware UTC datetime."""
    naive_dt = datetime(2023, 1, 1, 12, 0, 0)  # noqa: DTZ001

    utc_dt = make_datetime_utc(naive_dt)

    assert utc_dt.tzinfo == UTC
    assert utc_dt == datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_make_datetime_utc_with_aware_datetime():
    """Test that an aware datetime in a different timezone is converted to UTC correctly."""
    est = timezone(timedelta(hours=-5))

    aware_dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=est)

    utc_dt = make_datetime_utc(aware_dt)

    expected_utc_dt = datetime(2023, 1, 1, 17, 0, 0, tzinfo=UTC)

    assert utc_dt.tzinfo == UTC, "The timezone should be set to UTC"
    assert utc_dt == expected_utc_dt, f"The datetime should be {expected_utc_dt} in UTC"


@pytest.mark.asyncio
async def test_async_run_timeout():
    """Test that async_run returns None when a TimeoutError is raised."""
    mock_loop = MagicMock()
    mock_loop.run_in_executor.side_effect = TimeoutError

    with patch("asyncio.get_running_loop", return_value=mock_loop):
        result = await async_run(lambda: None)
        assert result is None
