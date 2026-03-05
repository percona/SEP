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

"""Define utilities related to importing modules and attributes."""

import importlib.util
from importlib import import_module
from typing import Any

__all__ = [
    "import_var",
    "validate_attribute_is_importable",
    "validate_importable_settings",
    "validate_module_is_importable",
]


def import_var(path: str) -> Any:
    """Dynamically import a variable from a given module path.

    Import and return an attribute from a module specified by its dot-separated
    path.

    :param path: The full dot-separated path to the variable (e.g.,
        "module.submodule.var_name").
    :type path: str
    :return: The imported variable.
    :rtype: Any
    :raises ImportError: If the module cannot be imported.
    :raises AttributeError: If the attribute does not exist in the module.
    """
    module_name, attr_name = path.rsplit(".", 1)
    module = import_module(module_name)
    return getattr(module, attr_name)


def validate_module_is_importable(module: str) -> str:
    """Validate importable module as string.

    :param module: The module path to validate.
    :type module: str
    :return: The validated module path.
    :rtype: str
    :raises ValueError: If the module cannot be found.
    """
    if importlib.util.find_spec(module) is None:
        raise ValueError(f"No module named {module}")
    return module


def validate_attribute_is_importable(attr_path: str) -> str:
    """Validate that a module.attribute path has a valid module.

    Only the module component is validated at construction time. Full attribute
    validation (module + attribute) is deferred to startup via
    `validate_importable_settings` to avoid circular imports during settings
    construction.

    :param attr_path: The module.attribute string to validate.
    :type attr_path: str
    :return: The validated module.attribute string.
    :rtype: str
    :raises ValueError: If the format is incorrect or the module cannot be found.
    """
    if attr_path:
        try:
            module_name, _ = attr_path.rsplit(".", 1)
        except ValueError as exc:
            raise ValueError(
                "Must follow the format module.class",
            ) from exc
        else:
            validate_module_is_importable(module_name)
    return attr_path


def validate_importable_settings(*attr_paths: str) -> None:
    """Validate that attribute paths resolve to real attributes.

    Call `import_var` on each path to verify that both the module and the
    attribute exist. Intended to be called at startup after all modules are
    loaded, avoiding the circular imports that prevent full validation during
    settings construction.

    :param attr_paths: Dot-separated module.attribute paths to validate.
    :type attr_paths: str
    :raises ImportError: If a module cannot be imported.
    :raises AttributeError: If an attribute does not exist in its module.
    """
    for path in attr_paths:
        import_var(path)
