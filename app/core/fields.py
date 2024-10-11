"""Define reusable fields and validators."""

import importlib.util
import logging
from datetime import timedelta
from enum import IntEnum
from os import PathLike
from pathlib import Path
from typing import Annotated
from typing import Self

from pydantic import AfterValidator
from pydantic import BeforeValidator
from pydantic import DirectoryPath
from pydantic import Field
from pydantic import FilePath
from pydantic import GetCoreSchemaHandler
from pydantic import HttpUrl
from pydantic import PlainSerializer
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema
from starlette.datastructures import URL as StarletteURL  # noqa: N811


class URL(StarletteURL):
    """Define a custom URL type with Pydantic validation.

    This class extends Starlette's `URL` class and integrates custom validation
    for use with Pydantic models. It ensures that only valid URLs are accepted
    and provides a custom schema for Pydantic's core validation.

    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: type,
        handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(cls.validate_url)

    @classmethod
    def validate_url(cls, v: str) -> Self:
        """Validate the provided URL string and return a URL instance.

        Attempt to create a `URL` instance from the given string. Raise a
        `ValueError` if the URL is invalid.

        :param v: The URL string to validate.
        :type v: str
        :return: The validated `URL` instance.
        :rtype: URL
        :raises ValueError: If the provided string is not a valid URL.
        """
        try:
            return cls(v)
        except ValueError:
            raise ValueError(f"Invalid URL: {v}") from None

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: core_schema.CoreSchema,
        handler: GetCoreSchemaHandler,
    ) -> JsonSchemaValue:
        json_schema = handler(core_schema)
        json_schema.update(
            {
                "type": "string",
                "format": "uri",
            },
        )
        return json_schema


class LogLevelEnum(IntEnum):
    """Enumeration of logging levels."""

    CRITICAL = logging.CRITICAL
    FATAL = logging.CRITICAL
    ERROR = logging.ERROR
    WARNING = logging.WARNING
    WARN = logging.WARNING
    INFO = logging.INFO
    DEBUG = logging.DEBUG
    NOTSET = logging.NOTSET
    DISABLED = logging.NOTSET


def resolve_relative_path(v: PathLike | str) -> Path:
    """Resolve relative paths with BASE_DIR.

    :param v: The relative path to resolve.
    :type v: PathLike | str
    :return: The resolved absolute path.
    :rtype: Path
    :raises ValueError: If the path cannot be resolved.
    """
    try:
        return Path(__file__).resolve().parent.parent.parent / v
    except TypeError as exc:
        raise ValueError from exc


def validate_http_url(v: str) -> str:
    """Validate HTTP URL as string.

    :param v: The URL string to validate.
    :type v: str
    :return: The validated URL string without trailing slashes.
    :rtype: str
    :raises ValueError: If the URL is invalid.
    """
    url = HttpUrl(v)
    return str(url).strip("/")


def validate_module_is_importable(v: str) -> str:
    """Validate importable module as string.

    :param v: The module path to validate.
    :type v: str
    :return: The validated module path.
    :rtype: str
    :raises ValueError: If the module cannot be found.
    """
    if importlib.util.find_spec(v) is None:
        raise ValueError(f"No module named {v}")
    return v


def validate_attribute_is_importable(v: str) -> str:
    """Validate importable module.attribute as string.

    :param v: The module.attribute string to validate.
    :type v: str
    :return: The validated module.attribute string.
    :rtype: str
    :raises ValueError: If the format is incorrect or the module cannot be found.
    """
    # TODO: Find a way to validate attribute without circular import
    if v:
        try:
            module_name, _ = v.rsplit(".", 1)
        except ValueError as exc:
            raise ValueError(
                "Must follow the format module.class",
            ) from exc
        else:
            validate_module_is_importable(module_name)
    return v


def empty_str_to_none(v: str | None) -> str | None:
    """Return None if string is empty.

    :param v: The string to check.
    :type v: str | None
    :return: None if the string is empty, otherwise the string itself.
    :rtype: str | None
    """
    if v == "":
        return None
    return v


def remove_duplicates(v: list) -> list:
    """Remove duplicates from a list while maintaining order.

    :param v: The list to remove duplicates from.
    :type v: list
    :return: The list without duplicates.
    :rtype: list
    """
    unique_list = []
    for item in v:
        if item not in unique_list:
            unique_list.append(item)
    return unique_list


def validate_log_level(v: LogLevelEnum | str) -> LogLevelEnum:
    """Validate and return the logging level.

    :param v: The logging level to validate.
    :type v: LogLevelEnum | str
    :return: The validated logging level as LogLevelEnum.
    :rtype: LogLevelEnum
    :raises ValueError: If the logging level is invalid.
    """
    if isinstance(v, LogLevelEnum):
        return v
    try:
        return LogLevelEnum[v.upper()]
    except KeyError as exc:
        raise ValueError(f"Invalid log level: '{v}'") from exc


RelativeFilePath = Annotated[
    FilePath,
    BeforeValidator(resolve_relative_path),
    Field(validate_default=True),
]
RelativeDirectoryPath = Annotated[
    DirectoryPath,
    BeforeValidator(resolve_relative_path),
    Field(validate_default=True),
]
StrHttpUrl = Annotated[str, AfterValidator(validate_http_url)]
StrImportableModule = Annotated[str, AfterValidator(validate_module_is_importable)]
StrImportableAttribute = Annotated[
    str,
    AfterValidator(validate_attribute_is_importable),
]
RequiredStr = Annotated[str, Field(min_length=1)]
EmptyStrToNone = Annotated[None, BeforeValidator(empty_str_to_none)]
URIPath = Annotated[str, Field(pattern=r"^\/[^\s]*$")]
TimedeltaSeconds = Annotated[
    timedelta,
    PlainSerializer(lambda v: round(v.total_seconds()), return_type=int),
]
LogLevel = Annotated[LogLevelEnum, BeforeValidator(validate_log_level)]
