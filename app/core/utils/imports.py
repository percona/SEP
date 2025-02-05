"""Define utilities related to importing modules and attributes."""

import importlib.util
from importlib import import_module
from typing import Any

__all__ = [
    "import_var",
    "validate_attribute_is_importable",
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
    """Validate importable module.attribute as string.

    :param attr_path: The module.attribute string to validate.
    :type attr_path: str
    :return: The validated module.attribute string.
    :rtype: str
    :raises ValueError: If the format is incorrect or the module cannot be found.
    """
    # TODO: Find a way to validate attribute without circular import  # noqa: TD002, TD003
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
