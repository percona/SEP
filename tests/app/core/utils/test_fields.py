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

"""Define tests for the app.core.fields module."""

import pytest

from app.core.utils.fields import URL
from app.core.utils.imports import (
    validate_attribute_is_importable,
    validate_module_is_importable,
)
from app.core.utils.path import resolve_relative_path


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
    with pytest.raises(ValueError, match="Unable to resolve path: None"):
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
