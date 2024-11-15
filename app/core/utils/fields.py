"""Define reusable fields, validators, and related utilities."""

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, IntEnum, StrEnum
from typing import Annotated, Any, Generic, Self, TypeVar

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
    TypeAdapter,
    UrlConstraints,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema, Url
from starlette.datastructures import URL as StarletteURL  # noqa: N811

from app.core.utils.datetime import make_datetime_utc
from app.core.utils.imports import (
    validate_attribute_is_importable,
    validate_module_is_importable,
)
from app.core.utils.path import resolve_relative_path

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
T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class AsTypeValidator:
    """Validate an object with a specified class and optionally apply post-processing.

    This validator uses a designated type (`validate_class`) to validate an object. If a
    post-processing function is provided, it applies this function to the validated
    value before returning it. Otherwise, it returns the original object.

    :param validate_class: The class to use for validation.
    :type validate_class: type[V]
    :param post_processing: An optional callable to process the validated value.
        Defaults to None.
    :type post_processing: Callable[[V], R] | None
    """

    validate_class: type[V]
    post_processing: Callable[[V], R] | None = None

    def validate_as_type(self, obj: T) -> T | R:
        """Validate an object with `self.validate_class` and return the result.

        This method validates an object with `self.validate_class` and returns
        `self.post_processing(validated_value)` if `self.post_processing` is defined.
        If `self.post_processing` is None, the initial object is returned as is.

        :param obj: The object to validate.
        :type obj: T
        :return: The return of `self.post_processing(validated_value)` if
            `self.post_processing` is defined, or `obj` if not.
        :rtype: T | R
        :raises ValidationError: If the validation fails.
        """
        validated_value = TypeAdapter(self.validate_class).validate_python(obj)
        if self.post_processing is None:
            return obj
        return self.post_processing(validated_value)

    def __get_pydantic_core_schema__(
        self, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """Provide the Pydantic core schema for the validator.

        This method integrates the `validate_as_type` method into Pydantic's
        validation schema.

        :param source_type: The source type for validation.
        :type source_type: Any
        :param handler: The handler for core schema retrieval.
        :type handler: GetCoreSchemaHandler
        :return: The core schema incorporating the validation logic.
        :rtype: core_schema.CoreSchema
        """
        return core_schema.no_info_after_validator_function(
            self.validate_as_type, handler(source_type)
        )


class URL(StarletteURL):
    """Define a custom URL type with Pydantic validation.

    This class extends Starlette's `URL` class and integrates custom validation
    for use with Pydantic models. It ensures that only valid URLs are accepted
    and provides a custom schema for Pydantic's core validation.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        """Provide the Pydantic core schema for URL validation.

        This method integrates the `validate_url` method into Pydantic's
        validation schema.

        :param source_type: The source type for validation.
        :type source_type: Any
        :param handler: The handler for core schema retrieval.
        :type handler: GetCoreSchemaHandler
        :return: The core schema incorporating the URL validation logic.
        :rtype: core_schema.CoreSchema
        """
        return core_schema.no_info_plain_validator_function(cls.validate_url)

    @classmethod
    def validate_url(cls, url: str) -> Self:
        """Validate the provided URL string and return a URL instance.

        Attempt to create a `URL` instance from the given string. Raise a
        `ValueError` if the URL is invalid.

        :param url: The URL string to validate.
        :type url: str
        :return: The validated `URL` instance.
        :rtype: URL
        :raises ValueError: If the provided string is not a valid URL.
        """
        try:
            return cls(url)
        except ValueError:
            raise ValueError(f"Invalid URL: {url}") from None

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: core_schema.CoreSchema,
        handler: GetCoreSchemaHandler,
    ) -> JsonSchemaValue:
        """Provide the JSON schema for the custom URL type.

        This method defines the JSON schema properties for the `URL` type, specifying
        that it should be treated as a string with a URI format.

        :param core_schema: The core schema for the URL.
        :type core_schema: core_schema.CoreSchema
        :param handler: The handler for JSON schema retrieval.
        :type handler: GetCoreSchemaHandler
        :return: The JSON schema for the `URL` type.
        :rtype: JsonSchemaValue
        """
        json_schema = handler(core_schema)
        json_schema.update(
            {
                "type": "string",
                "format": "uri",
            },
        )
        return json_schema


class UniqueList(list[T], Generic[T]):
    """A list subclass that ensures all elements are unique.

    This class can be used with type parameters (e.g., `UniqueList[int]`) to create
    a list type where duplicates are automatically removed.
    """

    def __init__(self, iterable: Iterable[T] = ()) -> None:
        """Initialize the UniqueList, removing duplicates from the provided iterable.

        :param iterable: The iterable to remove duplicates from.
        :type iterable: Iterable[T]
        """
        unique_list = []
        for item in iterable:
            if item not in unique_list:
                unique_list.append(item)
        super().__init__(unique_list)

    def __setitem__(self, index: int, value: T) -> None:
        """Set an item at a specific index, ensuring uniqueness.

        If the value already exists in the list at a different index, it removes the
        existing occurrence before setting the new value.

        :param index: The index at which to set the value.
        :type index: int
        :param value: The value to set.
        :type value: T
        """
        if value in self and index != (current_index := self.index(value)):
            super().__setitem__(index, value)
            self.pop(current_index)
        else:
            super().__setitem__(index, value)

    def __add__(self, other: list[T]) -> "UniqueList[T]":
        """Concatenate two lists into a new UniqueList.

        :param other: The list to concatenate.
        :type other: list[T]
        :return: A new `UniqueList` containing elements from both lists without
            duplicates.
        :rtype: UniqueList[T]
        """
        return UniqueList(list(self) + list(other))

    def __iadd__(self, other: list[T]) -> Self:
        """Extend the UniqueList in-place with elements from another list.

        :param other: The list of elements to add.
        :type other: list[T]
        :return: The updated `UniqueList` instance.
        :rtype: Self
        """
        self.extend(other)
        return self

    def append(self, value: T) -> None:
        """Append a value to the UniqueList if it's not already present.

        :param value: The value to append.
        :type value: T
        """
        if value not in self:
            super().append(value)

    def extend(self, iterable: Iterable[T]) -> None:
        """Extend the UniqueList with elements from an iterable, ensuring uniqueness.

        :param iterable: The iterable of elements to add.
        :type iterable: Iterable[T]
        """
        super().extend(value for value in iterable if value not in self)

    def insert(self, index: int, value: T) -> None:
        """Insert a value at a specific index if it's not already present.

        :param index: The index at which to insert the value.
        :type index: int
        :param value: The value to insert.
        :type value: T
        """
        if value not in self:
            super().insert(index, value)


class EnumFieldMixin:
    """Provide a Pydantic core schema for Enum fields.

    This mixin integrates Enum validation into Pydantic's validation schema
    by utilizing the `get_enum_from_value_or_name_factory`.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls: type[Enum],
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        """Provide the Pydantic core schema for Enum validation.

        This method applies a before-validator function that retrieves Enum members
        based on their value or name.

        :param source_type: The source type for validation.
        :type source_type: Any
        :param handler: The handler for core schema retrieval.
        :type handler: GetCoreSchemaHandler
        :return: The core schema incorporating the Enum validation logic.
        :rtype: core_schema.CoreSchema
        """
        return core_schema.no_info_before_validator_function(
            get_enum_from_value_or_name_factory(cls), handler(source_type)
        )


class LogLevel(EnumFieldMixin, IntEnum):
    """Enumerate standard logging levels.

    This enumeration maps common logging level names to their corresponding
    integer values as defined in Python's `logging` module.

    :cvar CRITICAL: Critical logging level.
    :vartype CRITICAL: int
    :cvar FATAL: Fatal logging level (alias for CRITICAL).
    :vartype FATAL: int
    :cvar ERROR: Error logging level.
    :vartype ERROR: int
    :cvar WARNING: Warning logging level.
    :vartype WARNING: int
    :cvar WARN: Warn logging level (alias for WARNING).
    :vartype WARN: int
    :cvar INFO: Info logging level.
    :vartype INFO: int
    :cvar DEBUG: Debug logging level.
    :vartype DEBUG: int
    :cvar NOTSET: Notset logging level.
    :vartype NOTSET: int
    :cvar DISABLED: Disabled logging level (alias for NOTSET).
    :vartype DISABLED: int
    """

    CRITICAL = logging.CRITICAL
    FATAL = logging.CRITICAL
    ERROR = logging.ERROR
    WARNING = logging.WARNING
    WARN = logging.WARNING
    INFO = logging.INFO
    DEBUG = logging.DEBUG
    NOTSET = logging.NOTSET
    DISABLED = logging.NOTSET


class DatabaseEngine(EnumFieldMixin, StrEnum):
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


class AsyncDatabaseEngine(EnumFieldMixin, StrEnum):
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


def database_url_normalized_scheme_field_factory(
    engine_enum_class: type[DatabaseEngine] | type[AsyncDatabaseEngine],
) -> type[Url]:
    """Generate and return an Url field that normalizes the scheme of a database URL.

    This factory function generates an annotated Url field with a BeforeValidator that
    normalizes the scheme of a database URL according to the `engine_enum_class`
    specified.

    :param engine_enum_class: The database engine enum type to use. Either
        `DatabaseEngineEnum` or `AsyncDatabaseEngineEnum`.
    :type engine_enum_class: type[DatabaseEngineEnum] | type[AsyncDatabaseEngineEnum]
    :return: The annotated Url field with the attached validator.
    :rtype: type[Url]
    """
    get_database_engine_enum = get_enum_from_value_or_name_factory(engine_enum_class)

    def normalize_database_url_scheme(db_url: Any) -> Any:
        """Normalize the scheme of the provided database URL.

        If the URL starts with a recognized scheme, it replaces it with the normalized
        scheme based on the `engine_enum_class`. Otherwise, it returns the URL
        unchanged.

        :param db_url: The database URL to normalize.
        :type db_url: Any
        :return: The normalized database URL.
        :rtype: Any
        """
        if not isinstance(db_url, str):
            return db_url
        pattern = re.compile(r"^(([a-zA-Z]+)(?:\+[a-zA-Z0-9]+)?)://")
        match = pattern.match(db_url)
        if not match:
            return db_url
        base_scheme = match.group(2)
        return pattern.sub(f"{get_database_engine_enum(base_scheme)}://", db_url)

    return Annotated[
        Url,
        UrlConstraints(allowed_schemes=list(engine_enum_class)),
        BeforeValidator(normalize_database_url_scheme),
    ]


RequiredStr = Annotated[str, Field(min_length=1)]
"""Define a string field that must not be empty."""

EmptyStrToNone = Annotated[None, BeforeValidator(lambda v: None if v == "" else v)]
"""Convert empty strings to None."""

RelativeFilePath = Annotated[
    FilePath,
    BeforeValidator(resolve_relative_path),
    Field(validate_default=True),
]
"""Define a file path that resolves relative paths.

This annotated type ensures that the provided file path is valid and resolves
relative paths based on the application's directory structure.
"""

RelativeDirectoryPath = Annotated[
    DirectoryPath,
    BeforeValidator(resolve_relative_path),
    Field(validate_default=True),
]
"""Define a directory path that resolves relative paths.

This annotated type ensures that the provided directory path is valid and resolves
relative paths based on the application's directory structure.
"""

DatabaseUrl = database_url_normalized_scheme_field_factory(DatabaseEngine)
"""Define a normalized synchronous database URL.

This annotated type normalizes the scheme of the database URL based on the
`synchronous` database engines defined in `DatabaseEngine`.
"""

AsyncDatabaseUrl = database_url_normalized_scheme_field_factory(AsyncDatabaseEngine)
"""Define a normalized asynchronous database URL.

This annotated type normalizes the scheme of the database URL based on the
`asynchronous` database engines defined in `AsyncDatabaseEngine`.
"""

StrDatabaseUrl = Annotated[str, AsTypeValidator(DatabaseUrl, str)]
"""Define a string field representing a synchronous database URL.

This annotated type validates the string as a synchronous database URL and
ensures it is returned as a string.
"""

StrAsyncDatabaseUrl = Annotated[str, AsTypeValidator(AsyncDatabaseUrl, str)]
"""Define a string field representing an asynchronous database URL.

This annotated type validates the string as an asynchronous database URL and
ensures it is returned as a string.
"""

StrHttpUrl = Annotated[str, AsTypeValidator(HttpUrl, lambda v: str(v).rstrip("/"))]
"""Define a string field representing an HTTP URL.

This annotated type validates the string as an HTTP URL and removes any trailing
slashes from the URL.
"""

StrAnyUrl = Annotated[str, AsTypeValidator(AnyUrl, str)]
"""Define a string field representing any valid URL.

This annotated type validates the string as any valid URL without additional processing.
"""

URIPath = Annotated[str, Field(pattern=r"^\/[^\s]*$")]
"""Define a string field representing a URI path.

This annotated type ensures that the string starts with a forward slash and does
not contain any whitespace characters.
"""

StrImportableModule = Annotated[str, AfterValidator(validate_module_is_importable)]
"""Define a string field representing an importable module.

This annotated type validates that the string corresponds to a module that can be
imported.
"""

StrImportableAttribute = Annotated[
    str,
    AfterValidator(validate_attribute_is_importable),
]
"""Define a string field representing an importable attribute.

This annotated type validates that the string corresponds to an attribute that can be
imported.
"""

TimedeltaSeconds = Annotated[
    timedelta,
    PlainSerializer(lambda v: round(v.total_seconds()), return_type=int),
]
"""Define a timedelta field serialized as total seconds.

This annotated type serializes a `timedelta` object to an integer representing the
total number of seconds.
"""

UTCDatetime = Annotated[datetime, AfterValidator(make_datetime_utc)]
"""Define a datetime field converted to UTC.

This annotated type ensures that the `datetime` object is converted to UTC timezone.
"""
