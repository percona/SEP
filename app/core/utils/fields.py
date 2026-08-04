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

"""Define reusable fields, validators, and related utilities."""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, IntEnum, StrEnum
from pathlib import Path
from typing import Annotated, Any, Self, TypeVar
from urllib.parse import urlparse, urlunparse

from annotated_types import Interval
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
    StringConstraints,
    TypeAdapter,
    UrlConstraints,
    WrapSerializer,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema, Url
from starlette.datastructures import URL as StarletteURL  # noqa: N811

from app.core.utils.date_time import make_datetime_utc
from app.core.utils.imports import (
    validate_attribute_is_importable,
    validate_module_is_importable,
)
from app.core.utils.iterators import unique_everseen
from app.core.utils.json_pointer import validate_json_pointer
from app.core.utils.path import resolve_relative_path

E = TypeVar("E", bound=Enum)


def value_is_present(value: Any) -> bool:
    """Return whether ``value`` counts as *present* to a presence/forbidden gate.

    Treats ``None``, ``False``, and empty strings/bytes/lists/tuples/sets/dicts
    as absent. ``0`` counts as present (numeric, just falsy). ``False`` is
    treated as the unset bool default so ``forbidden=`` ``FieldGate`` entries on
    a ``BoolField`` fire only on an explicit ``True`` toggle, matching the
    convention used by ``FailRule`` ``truthy(name)`` checks.

    Shared by the framework's runtime gate evaluation (``_field_is_present``)
    and authoring-time guards (such as the snippets plugin's meta validation) so
    the two presence checks cannot drift. It lives here, in the core utilities,
    rather than the framework package so core models can reuse it without
    importing the plugin layer.

    :param value: The value to classify.
    :return: Whether the value is considered present.
    """
    if value is None or value is False:
        return False
    return not (
        isinstance(value, str | bytes | list | tuple | set | frozenset | dict)
        and not value
    )


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
        :raises ValueError: If `value_or_name` is not a value in {enum_class} and
            `value_or_name` is not a valid name for an Enum (not a string).
        :raises ValueError: If `value_or_name` is neither a value nor a name in
            {enum_class}.
        """
        try:
            return enum_class(value_or_name)
        except ValueError:
            if not isinstance(value_or_name, str):
                raise ValueError(
                    f"Value not found and is not a valid name for {enum_class_name}: {value_or_name!r}"
                ) from None
            enum_dict = {
                name.upper(): value for name, value in enum_class.__members__.items()
            }
            try:
                return enum_dict[value_or_name.upper()]
            except KeyError:
                raise ValueError(
                    f"Value and name not found for {enum_class_name}: {value_or_name!r}"
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
        """Provide the Pydantic core schema for URL validation and serialization.

        Integrate the ``validate_url`` method into Pydantic's validation schema
        and serialize URL values to their string form in JSON mode, so a
        ``URL``-typed value round-trips through ``model_dump(mode="json")``.

        :param source_type: The source type for validation.
        :type source_type: Any
        :param handler: The handler for core schema retrieval.
        :type handler: GetCoreSchemaHandler
        :return: The core schema incorporating the URL validation logic.
        :rtype: core_schema.CoreSchema
        """
        return core_schema.no_info_plain_validator_function(
            cls.validate_url,
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, when_used="json"
            ),
        )

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


class DatabaseDialect(EnumFieldMixin, StrEnum):
    """Enum representing supported database dialect names."""

    SQLITE = "sqlite"
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"


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


NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
"""Define a string field that must not be empty."""

ARBITRARY_ARGS_SCHEMA = {"additionalProperties": True}
"""Advertise a free-form argument map for OpenAPI / TypeScript clients.

Without this, a bare ``dict`` field emits ``type: object`` with no
``additionalProperties``, which openapi-typescript turns into
``Record<string, never>``. Pass as ``Field(json_schema_extra=...)`` on a plain
Pydantic field, or nest under ``SQLField(..., schema_extra=...)`` for SQLModel.
"""


class ArbitraryMapping(dict):
    """Open ``dict[str, Any]`` with ``additionalProperties`` in the object branch.

    Use for nested or nullable mappings, and for route-level free-form JSON
    bodies / responses. Putting ``additionalProperties`` only as a sibling of
    ``anyOf`` still leaves ``Record<string, never>`` in the generated union.

    Implemented as a ``dict`` subclass (not ``Annotated`` + ``WithJsonSchema``)
    for two reasons:

    1. **Fresh schema dicts.** FastAPI writes an operation-derived ``title``
       into the JSON schema it resolves for a return type or ``Body()``.
       ``WithJsonSchema`` returns the dict it stores, and equal metadata
       collapses across annotation sites, so one route's title leaks onto
       every other (including a GET response title on a PUT request body).
       An explicit ``title`` in the template, and a fresh dict *per*
       ``WithJsonSchema`` construction, both still leak. Returning a new dict
       from ``__get_pydantic_json_schema__`` on every call keeps titles local.
       Model fields are unaffected — they keep field-derived titles.
    2. **Stable component names.** The ``Annotated`` + ``WithJsonSchema`` form
       renamed generics to
       ``PaginatedResponse_Annotated_dict_str__Any___WithJsonSchema__``. A
       named subclass keeps ``PaginatedResponse_ArbitraryMapping_``.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        """Validate and coerce as a plain ``dict[str, Any]``.

        :param source_type: The annotated source type (ignored; always
            ``dict[str, Any]``).
        :param handler: Pydantic's core-schema builder.
        :return: A core schema for ``dict[str, Any]``.
        """
        return handler.generate_schema(dict[str, Any])

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: core_schema.CoreSchema,
        handler: GetCoreSchemaHandler,
    ) -> JsonSchemaValue:
        """Emit an open object schema, copying so FastAPI title writes stay local.

        :param core_schema: The core schema produced for this type.
        :param handler: Pydantic's JSON-schema builder.
        :return: A fresh ``type: object`` schema with ``additionalProperties``.
        """
        return {**handler(core_schema), **ARBITRARY_ARGS_SCHEMA}


def dsn_safe(value: str) -> str:
    """Reject DSN/CLI delimiters in a free-typed schema, table, or host name.

    Percona Toolkit DSN strings and comma-separated CLI arguments treat ``,``
    and ``=`` as structural delimiters. Free-solo reference fields accept either
    an inventory id (``int``) or a free-typed name (``str``); callers receiving
    ``int | str`` values should guard with ``isinstance(value, str)`` first.

    :param value: The free-typed name to validate.
    :return: ``value`` unchanged when it contains no delimiter.
    :raises ValueError: When ``value`` contains ``,`` or ``=``.
    """
    if "," in value or "=" in value:
        raise ValueError(
            "Values cannot contain ',' or '=' characters (DSN delimiters)."
        )
    return value


StrippedNonEmptyStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1)
]
"""Define a string field that strips surrounding whitespace and must not be empty."""

EmptyStrToNone = Annotated[None, BeforeValidator(lambda v: None if v == "" else v)]
"""Convert empty strings to None."""

TCP_PORT_MIN = 1
TCP_PORT_MAX = 65535

TcpPort = Annotated[int, Field(ge=TCP_PORT_MIN, le=TCP_PORT_MAX)]
"""Define a TCP port number constrained to the valid 1-65535 range."""


def bounded_int_from_empty_str_factory(ge: int, le: int | None = None) -> Any:
    """Build a bounded optional-int field type that coerces ``""`` to ``None``.

    The bounds sit at the returned type's outer ``Annotated`` level, carried by a single
    ``Interval`` container, so that Pydantic applies them only to real integers (not the
    coerced ``None``) and the form-DSL bounds scan reads them (it flattens
    ``GroupedMetadata`` containers such as ``Interval``). A plain
    ``int | EmptyStrToNone`` union cannot express this, hence a dedicated factory.

    :param ge: The inclusive lower bound applied to non-empty integer input.
    :param le: The inclusive upper bound; ``None`` leaves the field unbounded above.
    :return: An ``Annotated`` optional-int type carrying the bounds and blank coercion.
    """
    coerce_blank = BeforeValidator(lambda value: None if value == "" else value)
    return Annotated[int | None, Interval(ge=ge, le=le), coerce_blank]


RelativeFilePathField = Annotated[
    FilePath,
    BeforeValidator(resolve_relative_path),
    Field(validate_default=True),
]
"""Define a file path that resolves relative paths.

This annotated type ensures that the provided file path is valid and resolves
relative paths based on the application's directory structure.
"""

RelativeDirectoryPathField = Annotated[
    DirectoryPath,
    BeforeValidator(resolve_relative_path),
    Field(validate_default=True),
]
"""Define a directory path that resolves relative paths.

This annotated type ensures that the provided directory path is valid and resolves
relative paths based on the application's directory structure.
"""

RelativePathField = Annotated[
    Path,
    BeforeValidator(resolve_relative_path),
    Field(validate_default=True),
]
"""Define a path that resolves relative paths.

This annotated type ensures that the provided path is valid and resolves
relative paths based on the application's directory structure. This type does not
validate if the path exists, it only resolves the relative path to an absolute one.
"""

StrRelativePath = Annotated[str, AsTypeValidator(RelativePathField, str)]
"""Define a string field representing a relative paths.

This annotated type validates the string as a relative path and ensures it is returned
as a string.
"""

FilePathLike = Annotated[FilePath, BeforeValidator(lambda v: Path(v))]
"""Define a :class:`FilePath` that accepts any :class:`os.PathLike` object as input."""

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

CREDENTIAL_URL_MASK = "****"
PRESERVE_CREDENTIALS_CONTEXT: dict[str, bool] = {"preserve_credentials": True}


def _netloc_host(netloc: str) -> str:
    """Return the host portion of a URL netloc, preserving IPv6 bracket notation."""
    if "@" in netloc:
        _, host = netloc.rsplit("@", 1)
        return host
    return netloc


def redact_credential_url(url: str, *, mask: str = CREDENTIAL_URL_MASK) -> str:
    """Return ``url`` with any embedded userinfo password replaced by ``mask``.

    Scheme, username, host, port, path, query, and fragment are preserved.
    URLs without an embedded password are returned unchanged.

    :param url: The URL string to redact.
    :param mask: The replacement for the password segment.
    :return: The URL with a redacted password, or ``url`` when none is present.
    """
    parsed = urlparse(url)
    if not parsed.password:
        return url
    host = _netloc_host(parsed.netloc)
    username = parsed.username or ""
    netloc = f"{username}:{mask}@{host}"
    return urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _credential_url_identity_parts(
    parsed: Any, *, include_password: bool = True
) -> tuple[Any, ...]:
    """Return URL components used to detect an unchanged redacted resubmit."""
    path = parsed.path or ""
    if path == "/":
        path = ""
    parts: tuple[Any, ...] = (
        parsed.scheme,
        parsed.username or "",
        _netloc_host(parsed.netloc),
        path,
        parsed.params,
        parsed.query,
        parsed.fragment,
    )
    if include_password:
        return (*parts, parsed.password or "")
    return parts


def preserve_credential_url_password(current: str, incoming: str) -> str:
    """Keep the stored URL password when a PATCH resubmits the redacted display value.

    When the dashboard saves an endpoint unchanged, the client sends the JSON-redacted
    URL (``user:****@host``). Substitute the live password so the override row is
    not corrupted.

    :param current: The effective stored URL string.
    :param incoming: The URL string submitted in the PATCH body.
    :return: ``incoming`` unchanged unless it matches ``current`` with only the
        password masked.
    """
    current_str = str(current)
    incoming_str = str(incoming)
    current_parsed = urlparse(current_str)
    incoming_parsed = urlparse(incoming_str)
    if incoming_parsed.password != CREDENTIAL_URL_MASK:
        return incoming_str
    if not current_parsed.password:
        return incoming_str
    if _credential_url_identity_parts(current_parsed, include_password=False) != (
        _credential_url_identity_parts(incoming_parsed, include_password=False)
    ):
        return incoming_str
    return current_str


def _credential_url_serializer(
    value: Any,
    handler: Callable[[Any], Any],
    info: Any,
) -> Any:
    """Serialize a URL value, redacting embedded passwords unless context opts out."""
    serialized = handler(value)
    context = getattr(info, "context", None) or {}
    if context.get("preserve_credentials"):
        return serialized
    return redact_credential_url(str(serialized))


_CREDENTIAL_URL_JSON_SERIALIZER = WrapSerializer(
    _credential_url_serializer,
    when_used="json",
)


CredentialHttpUrl = Annotated[
    HttpUrl,
    _CREDENTIAL_URL_JSON_SERIALIZER,
]
"""Define an HTTP URL that redacts embedded userinfo passwords on JSON serialization.

The in-memory / python-mode value retains the real credential for outbound
requests. Pass :data:`PRESERVE_CREDENTIALS_CONTEXT` when dumping internal
config fingerprints that must store the full URL.
"""

StrCredentialHttpUrl = Annotated[
    str,
    AsTypeValidator(HttpUrl, lambda v: str(v).rstrip("/")),
    _CREDENTIAL_URL_JSON_SERIALIZER,
]
"""Define a string HTTP URL that redacts embedded passwords on JSON serialization.

Validates as :class:`~pydantic.HttpUrl`, stores as a string with trailing
slashes stripped, and masks any embedded password in JSON dumps.
"""

StrCredentialAnyUrl = Annotated[
    str,
    AsTypeValidator(AnyUrl, str),
    _CREDENTIAL_URL_JSON_SERIALIZER,
]
"""Define a string URL (any scheme) that redacts embedded passwords on JSON serialization.

Use for broker/backend URLs that may carry credentials in the userinfo segment.
"""

URIPath = Annotated[str, StringConstraints(pattern=r"^\/[^\s]*$")]
"""Define a string field representing a URI path.

This annotated type ensures that the string starts with a forward slash and does
not contain any whitespace characters.
"""

JsonPointerStr = Annotated[str, AfterValidator(validate_json_pointer)]
"""Define a string field holding an RFC 6901 JSON Pointer.

The empty string is the valid root pointer; any other value must start with a
forward slash and use ``~`` only in a ``~0`` or ``~1`` escape.
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

UniqueList = Annotated[list[T], AfterValidator(unique_everseen), AfterValidator(list)]
"""A list subclass that ensures all elements are unique.

This class can be used with type parameters (e.g., `UniqueList[int]`) to create
a list type where duplicates are automatically removed.
"""

UniqueTuple = Annotated[
    tuple[T, ...], AfterValidator(unique_everseen), AfterValidator(tuple)
]
"""A tuple subclass that ensures all elements are unique.

This class can be used with type parameters (e.g., `UniqueTuple[int]`) to create
a tuple type where duplicates are automatically removed.
"""

LenientStr = Annotated[str, BeforeValidator(str)]
"""A string field that accepts any input and converts it to a string."""

LowercaseStr = Annotated[str, StringConstraints(to_lower=True)]
"""A string field that is automatically converted to lowercase."""

FilenameExtension = Annotated[
    LowercaseStr, AfterValidator(lambda v: "." + v.lstrip("."))
]
"""A string field representing a filename extension.

This annotated type ensures that the string is lowercase and starts with a single dot.
"""

MimeType = Annotated[LowercaseStr, StringConstraints(pattern=r"^\w+\/[-+.\w]+$")]
"""A string type representing a MIME type.

This annotated type ensures that the string is lowercase and matches the MIME type
format.
"""
