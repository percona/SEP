"""Define tests for the app.core.utils.imports module."""

import sys
from importlib import util

import pytest

from app.core.utils import import_var


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
