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

"""Define tests for the app.core.utils.imports module."""

import sys
from importlib import util

import pytest

from app.core.utils import import_var
from app.core.utils.imports import (
    validate_attribute_is_importable,
    validate_importable_settings,
)


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


class TestValidateAttributeIsImportable:
    """Test `validate_attribute_is_importable` validator."""

    def test_valid_attribute_path(self):
        """Assert a valid module.attribute path passes validation."""
        result = validate_attribute_is_importable("os.path")
        assert result == "os.path"

    def test_invalid_module_raises(self):
        """Assert a non-existent module raises `ValueError`."""
        with pytest.raises(ValueError, match="No module named"):
            validate_attribute_is_importable("nonexistent_module.SomeClass")

    def test_invalid_format_raises(self):
        """Assert a path without a dot raises `ValueError`."""
        with pytest.raises(ValueError, match="Must follow the format"):
            validate_attribute_is_importable("nodots")

    def test_empty_string_passes(self):
        """Assert an empty string passes validation unchanged."""
        result = validate_attribute_is_importable("")
        assert result == ""


class TestValidateImportableSettings:
    """Test `validate_importable_settings` startup validator."""

    def test_valid_paths(self):
        """Assert valid attribute paths pass without errors."""
        validate_importable_settings("os.path", "sys.modules")

    def test_invalid_attribute_raises(self):
        """Assert a valid module with a non-existent attribute raises."""
        with pytest.raises(AttributeError):
            validate_importable_settings("os.nonexistent_attr")

    def test_invalid_module_raises(self):
        """Assert a non-existent module raises `ModuleNotFoundError`."""
        with pytest.raises(ModuleNotFoundError):
            validate_importable_settings("nonexistent_module.SomeClass")

    def test_mixed_valid_and_invalid_raises_on_first_invalid(self):
        """Assert validation stops at the first invalid path."""
        with pytest.raises(AttributeError):
            validate_importable_settings("os.path", "os.nonexistent_attr")

    def test_empty_string_skipped(self):
        """Assert empty strings are skipped without errors."""
        validate_importable_settings("", "os.path", "")

    def test_no_args(self):
        """Assert calling with no arguments succeeds."""
        validate_importable_settings()
