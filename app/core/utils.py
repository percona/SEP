"""Define core utility functions."""

import asyncio
import re
import unicodedata
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from http import HTTPStatus
from importlib import import_module
from typing import Any

LOG_FORMAT = "%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> %(module)s.%(funcName)s - %(message)s"
REFRESH_INTERVAL = 3600


def to_uppercase(name: str) -> str:
    """Convert a string to uppercase.

    This function takes a string input and returns a new string with all
    characters converted to uppercase.

    Parameters
    ----------
    name : str
        The string to be converted to uppercase.

    Returns
    -------
    str
        The input string converted to uppercase.

    """
    return name.upper()


# TODO: Update:
class ErrorFormatter:
    __storage = {}

    @property
    def details(self) -> dict:
        return self.__storage.get("details", {})

    @details.setter
    def details(self, details: dict):
        if not isinstance(details, dict):
            raise TypeError("details is not a dict")
        if "details" not in self.__storage or self.__storage["details"] != details:
            self.__storage["details"] = details

    def format_error_heading(self, details: dict) -> str:
        """Extract the error heading

        :param details:
        :return:
        """
        return self._format(details).phrase

    def format_error_message(self, details: dict) -> str:
        """Extract the error message

        :param details:
        :return:
        """
        return self._format(details).description

    def _format(self, details: dict) -> HTTPStatus:
        """:param details:
        :return:
        """
        self.details = details
        if "status_code" not in self.details:
            return HTTPStatus.NOT_FOUND
        return self._resolve_code(self.details["status_code"])

    @staticmethod
    def _resolve_code(code: int) -> HTTPStatus:
        """:param code:
        :return:
        """
        for status_code in HTTPStatus:
            if code == status_code.value:
                return status_code
        return HTTPStatus.NOT_FOUND


error_formatter = ErrorFormatter()
format_error_heading, format_error_message = (
    error_formatter.format_error_heading,
    error_formatter.format_error_message,
)


async def async_run(func: Callable, *args):
    """Execute a non-async call

    :param func:
    :param args:
    :param kwargs:
    :return:
    """

    async def _run_in_process(executor: ProcessPoolExecutor):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, func, *args)

    with ProcessPoolExecutor(max_workers=1) as pool:
        try:
            result = await asyncio.gather(_run_in_process(pool))
        except TimeoutError:
            result = None
    return result


def deep_dict_update(main_dict: dict[Any, Any], update_dict: dict[Any, Any]) -> None:
    """Recursively merge `update_dict` into `main_dict`.

    Update `main_dict` with the contents of `update_dict` recursively. For each key in
    `update_dict`, if the key exists in `main_dict` and both values are dictionaries,
    merge them recursively. If the key exists in `main_dict` and both values are lists,
    prepend the list from `update_dict` to the list in `main_dict`. Otherwise, overwrite
    the value in `main_dict` with the value from `update_dict`.

    Parameters
    ----------
    main_dict : dict[Any, Any]
        The dictionary to be updated.
    update_dict : dict[Any, Any]
        The dictionary containing updates to apply.

    """
    for key, value in update_dict.items():
        if (
            key in main_dict
            and isinstance(main_dict[key], dict)
            and isinstance(value, dict)
        ):
            deep_dict_update(main_dict[key], value)
        elif (
            key in main_dict
            and isinstance(main_dict[key], list)
            and isinstance(update_dict[key], list)
        ):
            main_dict[key] = update_dict[key] + main_dict[key]
        else:
            main_dict[key] = value


def deep_lowercase_dict_keys(data: dict[Any, Any]) -> dict[Any, Any]:
    """Recursively convert all string keys in a dictionary to lowercase.

    Traverse the input dictionary and convert all keys that are strings to lowercase.
    If a value is a dictionary, apply the conversion recursively.

    Parameters
    ----------
    data : dict[Any, Any]
        The dictionary whose keys are to be converted to lowercase.

    Returns
    -------
    dict[Any, Any]
        A new dictionary with all string keys converted to lowercase.

    """
    lowercase_dict = {}
    for key, value in data.items():
        new_key = key.lower() if isinstance(key, str) else key
        new_value = (
            deep_lowercase_dict_keys(value) if isinstance(value, dict) else value
        )
        lowercase_dict[new_key] = new_value
    return lowercase_dict


def slugify(text: str) -> str:
    """Convert a string into a slug suitable for URLs.

    Normalize the input text by removing non-ASCII characters, converting to lowercase,
    replacing non-alphanumeric characters with hyphens, and stripping leading/trailing
    hyphens.

    Parameters
    ----------
    text : str
        The string to convert into a slug.

    Returns
    -------
    str
        The slugified version of the input string.

    """
    slug = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("utf-8")
        .lower()
    )
    return re.sub(r"[^a-z0-9]+", "-", slug).strip("-")


def import_var(path: str) -> Any:
    """Dynamically import a variable from a given module path.

    Import and return an attribute from a module specified by its dot-separated path.

    Parameters
    ----------
    path : str
        The full dot-separated path to the variable (e.g., "module.submodule.var_name").

    Returns
    -------
    Any
        The imported variable.

    Raises
    ------
    ImportError
        If the module cannot be imported.
    AttributeError
        If the attribute does not exist in the module.

    """
    module_name, attr_name = path.rsplit(".", 1)
    module = import_module(module_name)
    return getattr(module, attr_name)
