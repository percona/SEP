"""Define reusable fields and validators."""

import importlib.util
import logging
from datetime import timedelta
from enum import IntEnum, StrEnum
from os import PathLike
from pathlib import Path
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AnyUrl,
    BeforeValidator,
    DirectoryPath,
    Field,
    FilePath,
    GetCoreSchemaHandler,
    HttpUrl,
    PlainSerializer,
    UrlConstraints,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema, Url
from starlette.datastructures import URL as StarletteURL  # noqa: N811

from app.core.utils import get_enum_from_value_or_name_factory, validate_as_type_factory


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


class AsyncDatabaseEngineEnum(StrEnum):
    """Enum representing supported async database engines.

    :cvar SQLITE: SQLite engine string, using the `aiosqlite` driver.
    :vartype SQLITE: str
    :cvar MYSQL: MySQL engine string, using the `aiomysql` driver.
    :vartype MYSQL: str
    :cvar POSTGRESQL: PostgreSQL engine string, using the `asyncpg` driver.
    :vartype POSTGRESQL: str
    """

    SQLITE = "sqlite+aiosqlite"
    MYSQL = "mysql+aiomysql"
    POSTGRESQL = "postgresql+asyncpg"


class DatabaseEngineEnum(StrEnum):
    """Enum representing supported database engines.

    :cvar SQLITE: SQLite engine string.
    :vartype SQLITE: str
    :cvar MYSQL: MySQL engine string, using the `pymysql` driver.
    :vartype MYSQL: str
    :cvar POSTGRESQL: PostgreSQL engine string, using the `psycopg2` driver.
    :vartype POSTGRESQL: str
    """

    SQLITE = "sqlite"
    MYSQL = "mysql+pymysql"
    POSTGRESQL = "postgresql+psycopg2"


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
    # TODO: Find a way to validate attribute without circular import  # noqa: TD002, TD003
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


RequiredStr = Annotated[str, Field(min_length=1)]
EmptyStrToNone = Annotated[None, BeforeValidator(empty_str_to_none)]

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

DatabaseUrl = Annotated[
    Url,
    UrlConstraints(allowed_schemes=list(DatabaseEngineEnum)),
]
AsyncDatabaseUrl = Annotated[
    Url,
    UrlConstraints(allowed_schemes=list(AsyncDatabaseEngineEnum)),
]
StrDatabaseUrl = Annotated[
    str, AfterValidator(validate_as_type_factory(DatabaseUrl, str))
]
StrAsyncDatabaseUrl = Annotated[
    str, AfterValidator(validate_as_type_factory(AsyncDatabaseUrl, str))
]
StrHttpUrl = Annotated[
    str, AfterValidator(validate_as_type_factory(HttpUrl, lambda v: str(v).rstrip("/")))
]
StrAnyUrl = Annotated[str, AfterValidator(validate_as_type_factory(AnyUrl, str))]
URIPath = Annotated[str, Field(pattern=r"^\/[^\s]*$")]
StrImportableModule = Annotated[str, AfterValidator(validate_module_is_importable)]
StrImportableAttribute = Annotated[
    str,
    AfterValidator(validate_attribute_is_importable),
]
TimedeltaSeconds = Annotated[
    timedelta,
    PlainSerializer(lambda v: round(v.total_seconds()), return_type=int),
]
LogLevel = Annotated[
    LogLevelEnum, BeforeValidator(get_enum_from_value_or_name_factory(LogLevelEnum))
]
DatabaseEngine = Annotated[
    DatabaseEngineEnum,
    BeforeValidator(get_enum_from_value_or_name_factory(DatabaseEngineEnum)),
]
AsyncDatabaseEngine = Annotated[
    AsyncDatabaseEngineEnum,
    BeforeValidator(get_enum_from_value_or_name_factory(AsyncDatabaseEngineEnum)),
]
