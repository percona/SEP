# Copyright 2026 Percona LLC
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
