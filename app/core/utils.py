"""Define core utility functions."""

import asyncio
import json
import re
import unicodedata
from base64 import b64encode
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from enum import Enum
from http import HTTPStatus
from importlib import import_module
from typing import Any, ClassVar, TypeVar

from fastapi.encoders import jsonable_encoder
from pydantic import TypeAdapter
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


def transform_dict_keys(
    data: dict[Any, Any], transform: Callable[[Any], Any], *, deep: bool = False
) -> dict[Any, Any]:
    """Transform all keys in a dictionary using a specified function.

    Traverse the input dictionary and transform all keys using the specified `transform`
    function. If a value is a dictionary and `deep` is True, apply the conversion
    recursively.

    :param data: The dictionary whose keys are to be transformed.
    :type data: dict[Any, Any]
    :param transform: The transform function to use.
    :type transform: Callable[[Any], Any]
    :param deep: If `True`, apply the transform function recursively to all sub-dicts.
        Defaults to False.
    :type deep: bool
    :return: A new dictionary with all keys transformed.
    :rtype: dict[Any, Any]
    """
    transformed_dict = {}
    for key, value in data.items():
        new_value = (
            transform_dict_keys(value, transform, deep=deep)
            if deep and isinstance(value, dict)
            else value
        )
        transformed_dict[transform(key)] = new_value
    return transformed_dict


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


def sort_dict(unsorted_dict: dict, key: Callable[[Any], Any]) -> dict:
    """Sort a dictionary based on a specified key function.

    This function returns a new dictionary with its items sorted according to the
    provided key function. The sorting is performed on the dictionary's items, and the
    resulting dictionary maintains the sorted order.

    :param unsorted_dict: The dictionary to be sorted.
    :type unsorted_dict: dict
    :param key: A function that extracts a comparison key from each dictionary item.
    :type key: Callable[[Any], Any]
    :return: A new dictionary sorted by the specified key function.
    :rtype: dict
    """
    return dict(sorted(unsorted_dict.items(), key=key))


def json_serializer(data: Any) -> str:
    """Serialize a Python object into a JSON-formatted string.

    This function encodes a given Python object using `jsonable_encoder`
    to ensure it is serializable, then converts it to a JSON string using `json.dumps`.

    :param data: The Python object to be serialized. This can be any JSON-serializable
        data type, such as dictionaries, lists, or primitive data types like
        integers, strings, and booleans.
    :type data: Any
    :return: A JSON-formatted string representing the serialized form of the input data.
    :rtype: str
    """
    return json.dumps(jsonable_encoder(data))


E = TypeVar("E", bound=Enum)


def get_enum_from_value_or_name_factory(enum_class: type[E]) -> Callable[[Any], E]:
    """Generate and return a function that returns the Enum from its value or name.

    :param enum_class: The Enum subclass to use.
    :type enum_class: type[E]
    :return: A function that returns the Enum value by name.
    :rtype: Callable[[Any], E]
    """
    enum_class_name = enum_class.__name__

    def get_enum_from_value_or_name(value_or_name: Any) -> enum_class:
        """Return the {enum_class} from its value or name.

        :param value_or_name: The value or name of the {enum_class} to return.
        :type value_or_name: Any
        :return: The {enum_class} found.
        :rtype: {enum_class}
        :raises ExceptionGroup[ValueError, TypeError]: If `value_or_name` is not a value
            in {enum_class} and `value_or_name` is not a valid name for an Enum (not a
            string).
        :raises ExceptionGroup[ValueError, KeyError]: If `value_or_name` is neither a
            value nor a name in {enum_class}.
        """
        try:
            return enum_class(value_or_name)
        except ValueError as exc_enum_value:
            if not isinstance(value_or_name, str):
                raise ExceptionGroup(
                    f"Value not found and is not a valid name for {enum_class_name}: {value_or_name!r}",
                    [
                        exc_enum_value,
                        TypeError(
                            f"{value_or_name!r} is not a valid name for {enum_class_name}"
                        ),
                    ],
                ) from None
            enum_dict = {enum_obj.name.upper(): enum_obj for enum_obj in enum_class}
            try:
                return enum_dict[value_or_name.upper()]
            except KeyError as exc_enum_name:
                raise ExceptionGroup(
                    f"Value and name not found for {enum_class_name}: {value_or_name!r}",
                    [exc_enum_value, exc_enum_name],
                ) from None

    get_enum_from_value_or_name.__doc__ = get_enum_from_value_or_name.__doc__.format(
        enum_class=enum_class_name
    )
    return get_enum_from_value_or_name


V = TypeVar("V")


def run_pydantic_type_validator(validate_class: type[V], obj: Any) -> V:
    """Perform Pydantic validation for the specified type with the specified object.

    This function validates a Python object against a Pydantic type and returns the
    validated object.

    :param: validate_class: The class to use for validation.
    :type validate_class: type[V]
    :param: obj: The Python object to validate.
    :type obj: Any
    :return: The validated object.
    :rtype: V
    """
    return TypeAdapter(validate_class).validate_python(obj)


T = TypeVar("T")
R = TypeVar("R")


def validate_as_type_factory(
    validate_class: type[V], post_processing: Callable[[V], R] | None = None
) -> Callable[[T], T | R]:
    """Generate and return a function that validates an object as a different type.

    :param validate_class: The class to use for validation.
    :type validate_class: type[V]
    :param post_processing: The post-processing callable to apply to the validated
        value, if any. Defaults to None, meaning the generated function will return the
        initial object as is.
    :type post_processing: V
    :return: A function that validates an object as a different type.
    :rtype: Callable[[T], T | R]
    """
    validate_class_name = str(validate_class)
    if post_processing is None:
        return_type = T
        doc_return_description = "`obj`"
        doc_first_line = (
            f"Validate an object as a {validate_class_name} and return it if valid"
        )
    else:
        return_type = R
        doc_return_description = (
            f"The return of `{post_processing.__name__}(validated_object)`"
        )
        doc_first_line = f"Validate an object as a {validate_class_name} and return `{post_processing.__name__}(validated_object)` if valid"
    return_class_name = return_type.__name__

    def validate_as_type(obj: T) -> return_type:
        """{first_line}.

        :param obj: The object to validate.
        :type obj: T
        :return: {return_description}.
        :rtype: {return_class}
        :raises ValidationError: If the validation fails.
        """
        validated_value = run_pydantic_type_validator(validate_class, obj)
        if post_processing is None:
            return obj
        return post_processing(validated_value)

    validate_as_type.__doc__ = validate_as_type.__doc__.format(
        first_line=doc_first_line,
        return_class=return_class_name,
        return_description=doc_return_description,
    )
    return validate_as_type
