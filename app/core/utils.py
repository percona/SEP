"""Define core utility functions."""

import asyncio
import re
import unicodedata
from base64 import b64encode
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from http import HTTPStatus
from importlib import import_module
from typing import Any, ClassVar

from python_minifier import minify

LOG_FORMAT = "%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> %(module)s.%(funcName)s - %(message)s"
REFRESH_INTERVAL = 3600


def to_uppercase(name: str) -> str:
    """Convert a string to uppercase.

    This function takes a string input and returns a new string with all
    characters converted to uppercase.

    :param name: The string to be converted to uppercase.
    :type name: str
    :return: The input string converted to uppercase.
    :rtype: str
    """
    return name.upper()


# TODO: Update:  # noqa: TD002, TD003
class ErrorFormatter:
    """Format HTTP errors based on provided details.

    The `ErrorFormatter` class provides methods to extract error headings
    and messages from error details, utilizing HTTP status codes for formatting.
    """

    __storage: ClassVar[dict] = {}

    @property
    def details(self) -> dict:
        """Get the current error details.

        :return: The current error details.
        :rtype: dict
        """
        return self.__storage.get("details", {})

    @details.setter
    def details(self, details: dict) -> None:
        """Set the error details.

        :param details: The error details to set.
        :type details: dict
        :raises TypeError: If `details` is not a dictionary.
        """
        if not isinstance(details, dict):
            raise TypeError("details is not a dict")
        if "details" not in self.__storage or self.__storage["details"] != details:
            self.__storage["details"] = details

    def format_error_heading(self, details: dict) -> str:
        """Extract the error heading from details.

        :param details: The error details.
        :type details: dict
        :return: The error heading.
        :rtype: str
        """
        return self._format(details).phrase

    def format_error_message(self, details: dict) -> str:
        """Extract the error message from details.

        :param details: The error details.
        :type details: dict
        :return: The error message.
        :rtype: str
        """
        return self._format(details).description

    def _format(self, details: dict) -> HTTPStatus:
        self.details = details
        if "status_code" not in self.details:
            return HTTPStatus.NOT_FOUND
        return self._resolve_code(self.details["status_code"])

    @staticmethod
    def _resolve_code(code: int) -> HTTPStatus:
        for status_code in HTTPStatus:
            if code == status_code.value:
                return status_code
        return HTTPStatus.NOT_FOUND


error_formatter = ErrorFormatter()
format_error_heading, format_error_message = (
    error_formatter.format_error_heading,
    error_formatter.format_error_message,
)


async def async_run(func: Callable, *args: Any) -> Any:
    """Execute a non-async function asynchronously.

    :param func: The function to execute.
    :type func: Callable
    :param args: Arguments to pass to the function.
    :type args: Any
    :return: The result of the function execution.
    :rtype: Any
    """

    async def _run_in_process(executor: ProcessPoolExecutor) -> Any:
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

    Update `main_dict` with the contents of `update_dict` recursively. For each
    key in `update_dict`, if the key exists in `main_dict` and both values are
    dictionaries, merge them recursively. If the key exists in `main_dict` and
    both values are lists, prepend the list from `update_dict` to the list in
    `main_dict`. Otherwise, overwrite the value in `main_dict` with the value
    from `update_dict`.

    :param main_dict: The dictionary to be updated.
    :type main_dict: dict[Any, Any]
    :param update_dict: The dictionary containing updates to apply.
    :type update_dict: dict[Any, Any]
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

    Traverse the input dictionary and convert all keys that are strings to
    lowercase. If a value is a dictionary, apply the conversion recursively.

    :param data: The dictionary whose keys are to be converted to lowercase.
    :type data: dict[Any, Any]
    :return: A new dictionary with all string keys converted to lowercase.
    :rtype: dict[Any, Any]
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

    Normalize the input text by removing non-ASCII characters, converting to
    lowercase, replacing non-alphanumeric characters with hyphens, and
    stripping leading/trailing hyphens.

    :param text: The string to convert into a slug.
    :type text: str
    :return: The slugified version of the input string.
    :rtype: str
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


def minify_file_content(content: str, file_ext: str = "") -> str:
    """Minify Python file content.

    Minify the given Python code string if the file extension is ".py" or not
    specified. For other file types, return the content unchanged.

    :param content: The content to be minified.
    :type content: str
    :param file_ext: The file extension indicating the type of content.
    :type file_ext: str, optional
    :return: The minified content if applicable, otherwise the original content.
    :rtype: str
    """
    file_ext = file_ext.lstrip(".").lower()
    if file_ext and file_ext != "py":
        return content
    try:
        return minify(
            content,
            remove_annotations=True,
            remove_pass=True,
            remove_literal_statements=True,
            combine_imports=True,
            hoist_literals=True,
            rename_locals=True,
            rename_globals=True,
            remove_object_base=True,
            remove_asserts=True,
            remove_debug=True,
            remove_explicit_return_none=True,
            remove_builtin_exception_brackets=True,
        )
    except SyntaxError:
        return content


def b64encode_str(value: str, encoding: str = "utf-8") -> str:
    """Encode a string to Base64.

    Encode the given string to Base64 format using the specified encoding.

    :param value: The string to be encoded.
    :type value: str
    :param encoding: The encoding to use for the string, defaults to "utf-8".
    :type encoding: str, optional
    :return: The Base64 encoded string.
    :rtype: str
    """
    return b64encode(value.encode(encoding)).decode(encoding)
