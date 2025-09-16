# Copyright (C) 2025 Percona LLC
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

"""Define the main models for the snippets feature as part of the SEP app."""

__all__ = ["BaseSnippetArgs", "Snippet", "SnippetExecutionMeta"]

import hashlib
import json
import logging
import shlex
from collections.abc import Iterable
from functools import cached_property
from io import SEEK_END
from os import PathLike
from pathlib import Path
from string import Template
from typing import Annotated, Any, ClassVar, NamedTuple, Self

import aiofiles
import yaml
from aiofiles.ospath import getsize
from async_lru import alru_cache
from pydantic import (
    BaseModel,
    BeforeValidator,
    computed_field,
    create_model,
    Field,
    PositiveInt,
    validate_call,
    ValidationError,
)
from sqlalchemy import Column, JSON
from sqlmodel import Field as SQLField

from app.core.db import BaseSQLModel
from app.core.db.models import DateTimeWithTimezone
from app.core.utils import (
    json_serializer,
    ttl_cache,
    utc_now,
)
from app.core.utils.fields import (
    EmptyStrToNone,
    FilePathLike,
    NonEmptyStr,
    StrAnyUrl,
    UTCDatetime,
)
from app.core.utils.pydantic import CustomFieldMetadata
from app.sep.snippets.config import SnippetFilterType, snippets_settings
from app.sep.snippets.forms import (
    FieldsetElement,
    FormElement,
    SelectElement,
    SubmitButtonElement,
    TextInputElement,
)
from app.sep.snippets.models.meta import (
    SnippetMetaParameter,
    SnippetMetaParametersValidationResult,
)
from app.sep.snippets.utils import generate_unique_identifiers, guess_mime_type

_ONE_HOUR = 60 * 60
_SEVEN_DAYS = 7 * 24 * _ONE_HOUR
EXECUTOR_HOSTS_INPUT_NAME = "-hostname-"
EXTRA_ARGS_INPUT_NAME = "-extra_args-"
EXTRA_ARGS_INPUT = TextInputElement(
    name=EXTRA_ARGS_INPUT_NAME,
    placeholder="e.g. --verbose",
    title="Any extra args to pass to the snippet execution command",
    label="Extra Args",
)

logger = logging.getLogger(__name__)

ExtraArgsField = Annotated[list[str], BeforeValidator(shlex.split)]


@validate_call
@ttl_cache(ttl=_SEVEN_DAYS, maxsize=4)
def get_executor_hosts_fieldset(executor_hosts: frozenset[str]) -> FieldsetElement:
    """Create a fieldset for executor hosts with a legend and input fields.

    :param executor_hosts: A set of executor host strings.
    :type executor_hosts: frozenset[str]
    :return: A FieldsetElement containing the input fields for the executor hosts.
    :rtype: FieldsetElement
    """
    return FieldsetElement(
        legend="Executor Host",
        children=[
            SelectElement(
                children=executor_hosts,
                name=EXECUTOR_HOSTS_INPUT_NAME,
                title="Select the hostname of the target system for snippet execution.",
                label="Select host",
                required=True,
            ),
        ],
    )


class FilePreview(NamedTuple):
    """A preview of a snippet's content.

    :param content: A preview of the snippet's content, limited to a certain number of
        characters and lines.
    :type content: str
    :param is_truncated: Whether the preview content is truncated (i.e., if the full
        content exceeds the preview limits).
    :type is_truncated: bool
    """

    content: str
    is_truncated: bool

    @classmethod
    @validate_call
    async def from_path(
        cls,
        path: FilePathLike,
        max_chars: PositiveInt,
        max_lines: PositiveInt,
        **_kwargs: Any,
    ) -> Self:
        """Create a FilePreview from a path.

        This function reads the file in the specified `path` and generates a preview of
        its content, limited to a certain number of characters and lines.

        :param path: The file path to read for generating the preview.
        :type path: PathLike
        :param max_chars: The maximum number of characters to include in the preview.
        :type max_chars: PositiveInt
        :param max_lines: The maximum number of lines to include in the preview.
        :type max_lines: PositiveInt
        :return: A `FilePreview` instance containing the preview content and whether it
            is truncated.
        :rtype: FilePreview
        """
        return await cls._from_path(path, max_chars, max_lines, **_kwargs)

    @classmethod
    @alru_cache(ttl=_ONE_HOUR, maxsize=16)
    async def _from_path(
        cls, path: Path, max_chars: int, max_lines: int, **_kwargs: Any
    ) -> Self:
        logger.debug("Generating preview for file: %s", path)
        async with aiofiles.open(path) as f:
            content = await f.readline()
            line_number = 1
            while len(content) < max_chars and line_number < max_lines:
                content += await f.readline()
                line_number += 1
            preview_content = content[:max_chars]
            is_truncated = content != preview_content or await f.tell() < await f.seek(
                0, SEEK_END
            )
        return cls(content=preview_content, is_truncated=is_truncated)


class BaseSnippetArgs(BaseModel):
    """Base model for validating snippet execution arguments.

    :cvar extra_args_field: The name of the field used to store extra arguments
        ("extra_args").
    :vartype extra_args_field: ClassVar[str]
    :param executor_host: The hostname of the target system where the snippet will be
        executed.
    :type executor_host: NonEmptyStr
    """

    extra_args_field: ClassVar[str] = "extra_args"
    executor_host: NonEmptyStr = Field(
        validation_alias=EXECUTOR_HOSTS_INPUT_NAME, exclude=True
    )

    def to_args_string(self) -> str:
        """Convert the model instance to a command-line argument string.

        :return: A string representing the command-line arguments.
        :rtype: str
        """
        args = [
            arg
            for field_identifier, value in self.model_dump(
                exclude={self.extra_args_field}, exclude_none=True
            ).items()
            for arg in self.format_args(field_identifier, value)
        ]
        return shlex.join(args + self.get_extra_args())

    def get_extra_args(self) -> list[str]:
        """Get the extra arguments from the model instance.

        :return: A list of extra arguments.
        :rtype: list[str]
        """
        return self.model_dump(include={self.extra_args_field}).get(
            self.extra_args_field, []
        )

    @classmethod
    def format_args(cls, field_identifier: str, value: Any) -> list[str]:
        """Format a field and its value as command-line arguments.

        :param field_identifier: The identifier of the field to format.
        :type field_identifier: str
        :param value: The value of the field to format.
        :type value: Any
        :return: A list of command-line arguments representing the field and its value.
        :rtype: list[str]
        """
        field_name, metadata = cls.get_field_metadata(field_identifier)
        if metadata.get("positional"):
            return [value]
        arg_template_mapping = {"value": shlex.quote(str(value))}
        if not (arg_format := metadata.get("arg_format")):
            if metadata.get("is_flag"):
                return [f"--{field_name}"] if value else []
            arg_format = snippets_settings.META.DEFAULT_ARG_FORMAT
            arg_template_mapping["name"] = field_name
        return shlex.split(Template(arg_format).safe_substitute(arg_template_mapping))

    @classmethod
    def get_field_metadata(cls, name: str) -> tuple[str, dict]:
        """Get the metadata for a specific field in the model.

        :param name: The name of the field to retrieve metadata for.
        :type name: str
        :return: A tuple containing the field's serialization alias (or name if no alias
            is set) and a dictionary of the field's metadata.
        :rtype: tuple[str, dict]
        """
        field = cls.model_fields[name]
        return field.serialization_alias or name, CustomFieldMetadata.field_to_dict(
            field, strict=True
        )


class Snippet(BaseSQLModel, table=True):
    """Represent a support snippet stored in the database.

    :param filename: The snippet filename. Must be unique.
    :type filename: str
    :param md5_digest: The MD5 hash digest of the snippet file.
    :type md5_digest: str
    :param approved_at: The approval time for the snippet, or None if the snippet is not
        approved.
    :type approved_at: UTCDatetime | None
    :param reason: The reason for the approval or disapproval of the snippet, if any.
        Defaults to "New snippet".
    :type reason: str
    :param meta: Additional metadata about the snippet, such as title, description,
        parameters, etc.
    :type meta: dict[str, Any]
    """

    filename: str = SQLField(min_length=1, max_length=255, unique=True, index=True)
    size: PositiveInt
    md5_digest: str = SQLField(min_length=32, max_length=32)
    approved_at: UTCDatetime | None = SQLField(
        sa_type=DateTimeWithTimezone,
        default=None,
        index=True,
    )
    updated_by: str | None = None
    reason: str = "New snippet"
    meta: dict[str, Any] = SQLField(
        sa_column=Column(JSON, nullable=False),
        default_factory=dict,
    )

    def __repr__(self) -> str:
        return f"'{self.filename}' ({self.md5_digest})"

    def __str__(self) -> str:
        return self.filename

    def __fspath__(self) -> str:
        return str(snippets_settings.SNIPPETS_DIR / self.filename)

    @computed_field
    @property
    def is_approved(self) -> bool:
        """Determine whether the snippet has been approved.

        :return: True if the snippet is approved (i.e. approved_at is not None), else
            False.
        :rtype: bool
        """
        return self.approved_at is not None

    @cached_property
    def title(self) -> str:
        """Get the title of the snippet.

        :return: The title of the snippet, or the filename if no title is specified in
            the metadata.
        :rtype: str
        """
        return self.meta.get("title", self.filename)

    @cached_property
    def description(self) -> str:
        """Get the description of the snippet.

        :return: The description of the snippet, or an empty string if no description is
            specified in the metadata.
        :rtype: str
        """
        return self.meta.get("description", "")

    @property
    def allow_extra_args(self) -> bool:
        """Determine whether extra arguments are allowed for the snippet.

        :return: `True` if extra arguments are allowed, else `False`. Defaults to the
            value specified in the snippets settings if not explicitly set in the
            metadata.
        :rtype: bool
        """
        return self.meta.get(
            "allow_extra_args", snippets_settings.META.DEFAULT_ALLOW_EXTRA_ARGS
        )

    @cached_property
    def path(self) -> Path:
        """Get the full path to the snippet file.

        :return: The full path to the snippet file.
        :rtype: Path
        """
        return Path(self)

    @cached_property
    def mime_type(self) -> str:
        """Get the MIME type of the snippet.

        :return: The MIME type of the snippet.
        :rtype: str
        """
        return guess_mime_type(self.path)

    @property
    def can_execute(self) -> bool:
        """Determine whether the snippet can be executed.

        A snippet can be executed if it is approved, it has a valid executor
        interpreter, and either parameter errors are ignored in the settings or there
        are no validation errors in the parameters.

        :return: `True` if the snippet can be executed, else `False`.
        :rtype: bool
        """
        return (
            self.is_approved
            and self.execution_interpreter is not None
            and (
                snippets_settings.META.IGNORE_INVALID_PARAMETERS
                or not self.validated_parameters.errors
            )
        )

    @cached_property
    def validated_parameters(self) -> SnippetMetaParametersValidationResult:
        """Get the validated parameters of the snippet.

        :return: A `SnippetMetaParametersValidationResult` instance containing the list
            of valid parameters and any validation errors encountered.
        :rtype: SnippetMetaParametersValidationResult
        """
        parameters = self.meta.get("parameters", [])
        return self._get_parameters_from_json(
            json_serializer(parameters, sort_keys=True),
        )

    @property
    def execution_interpreter(self) -> str | None:
        """Get the interpreter for executing the snippet.

        :return: The interpreter for executing the snippet, or None if no interpreter is
            found.
        :rtype: str | None
        """
        return self._get_execution_interpreter(self.path)

    async def get_preview(self) -> FilePreview:
        """Get a preview of the snippet code.

        :return: A :class:`FilePreview` instance containing a preview of the snippet
            code.
        :rtype: FilePreview
        """
        return await FilePreview.from_path(
            self,
            snippets_settings.PREVIEW_MAX_CHARS,
            snippets_settings.PREVIEW_MAX_LINES,
            file_hash=self.md5_digest,
        )

    async def update_from_snippet(self, snippet: "Snippet") -> None:
        """Update the current snippet from another snippet.

        :param snippet: The snippet from which to update.
        :type snippet: Snippet
        """
        self.sqlmodel_update(snippet, update={"id": self.id})
        self.meta = await self.get_meta_by_path(self)
        self.remove_approval("File contents have changed", None)

    def approve(self, reason: str, user_id: str) -> None:
        """Mark the snippet as approved.

        Set the snippet's approved_at to the current time and change the reason.

        :param reason: The reason for the approval of the snippet.
        :type reason: str
        :param user_id: The ID of the user approving the snippet.
        :type user_id: str
        """
        self.approved_at = utc_now()
        self.updated_by = user_id
        self.reason = reason

    def remove_approval(self, reason: str, user_id: str | None) -> None:
        """Mark the snippet as unapproved.

        Set the snippet's approved_at to None and change the reason.

        :param reason: The reason for the approval removal of the snippet.
        :type reason: str
        :param user_id: The ID of the user removing the approval of the snippet.
        :type user_id: str | None
        """
        self.approved_at = None
        self.updated_by = user_id
        self.reason = reason

    async def update_meta(self) -> None:
        """Update the snippet's metadata."""
        self.meta = await self.get_meta_by_path(self)

    def to_form(self, executor_hosts: Iterable[str], form_action: str = "") -> str:
        """Generate an HTML form for executing the snippet.

        This method creates a form with fields based on the snippet's metadata and
        the provided executor hosts. It includes a select element for choosing the
        executor host and fields for snippet parameters.

        :param executor_hosts: An iterable  of hostnames where the snippet can be
            executed.
        :type executor_hosts: Iterable[str]
        :param form_action: The action URL for the form submission. Defaults to an
            empty string.
        :type form_action: str
        :return: An HTML string representing the form for executing the snippet.
        :rtype: str
        """
        logger.debug(
            "Generating execution form for snippet %s (action=%r)", self, form_action
        )
        parameters = self.meta.get("parameters", [])
        logger.debug("Meta Snippet parameters: %s)", parameters)
        return self._to_form(
            json_serializer(parameters, sort_keys=True),
            executor_hosts,
            add_extra_args_field=self.allow_extra_args,
            form_action=form_action,
            disabled=not self.can_execute,
        )

    def get_execution_model(self) -> type[BaseSnippetArgs]:
        """Generate a Pydantic model for validating snippet execution parameters.

        This method creates a dynamic Pydantic model based on the snippet's metadata,
        which can be used to validate the parameters required for executing the snippet.

        :return: A Pydantic model class for validating the snippet's execution
            parameters.
        :rtype: type[BaseSnippetArgs]
        """
        parameters = self.meta.get("parameters", [])
        logger.debug("Meta Snippet parameters: %s)", parameters)
        return self._get_execution_model(
            json_serializer(parameters, sort_keys=True),
            add_extra_args_field=self.allow_extra_args,
        )

    @staticmethod
    async def get_meta_by_path(path: PathLike) -> dict[str, Any]:
        """Extract metadata from a snippet file.

        This method reads the first few lines of the file and extracts metadata
        according to the specified patterns. It returns a dictionary with the
        extracted metadata.

        :param path: The path to the snippet file.
        :type path: PathLike
        :return: A dictionary containing the extracted metadata.
        :rtype: dict[str, Any]
        """
        try:
            async with aiofiles.open(path) as f:
                line = await f.readline()
                front_matter_lines = None
                while not snippets_settings.META.STOP_SEARCH_PATTERN.match(line):
                    match = snippets_settings.META.LINE_PATTERN.match(line)
                    if match:
                        content = match.groupdict().get("line", match.group(0))
                        if content == snippets_settings.META.DELIMITER:
                            if front_matter_lines is not None:
                                break
                            front_matter_lines = []
                        elif front_matter_lines is not None:
                            front_matter_lines.append(content)
                    line = await f.readline()
            return (
                yaml.safe_load("\n".join(front_matter_lines))
                if front_matter_lines
                else {}
            )
        except UnicodeDecodeError:
            return {}

    @staticmethod
    @ttl_cache(ttl=_ONE_HOUR, maxsize=16)
    def _get_parameters_from_json(
        parameters_json: str,
    ) -> SnippetMetaParametersValidationResult:
        """Parse and validate snippet parameters from a JSON string.

        :param parameters_json: A JSON string representing a list of snippet parameters.
        :type parameters_json: str
        :return: A SnippetMetaParametersValidationResult instance containing the list of
            valid parameters and any validation errors encountered.
        :rtype: SnippetMetaParametersValidationResult
        """
        parameters = json.loads(parameters_json) or []
        if not isinstance(parameters, list):
            error_msg = f"Invalid snippet parameters, expected a list but got {parameters.__class__.__name__}"
            logger.warning("%s: %r", error_msg, parameters)
            return SnippetMetaParametersValidationResult(
                parameters=[], errors=[error_msg]
            )
        valid_parameters = []
        errors = []
        for param in parameters:
            try:
                valid_parameters.append(SnippetMetaParameter.model_validate(param))
            except ValidationError as exc:
                logger.warning("Invalid snippet parameter %r", param, exc_info=True)
                errors.extend(
                    SnippetMetaParameter.convert_validation_errors(exc, param)
                )
        return SnippetMetaParametersValidationResult(
            parameters=valid_parameters, errors=errors
        )

    @staticmethod
    @validate_call
    @ttl_cache(ttl=_ONE_HOUR, maxsize=16)
    def _to_form(
        parameters_json: str,
        executor_hosts: frozenset[str],
        *,
        add_extra_args_field: bool,
        form_action: str = "",
        disabled: bool = False,
    ) -> str:
        """Generate an HTML form for executing a snippet.

        This internal method creates a form with fields based on the snippet's
        parameters and the provided executor hosts. It includes a select element for
        choosing the executor host and fields for snippet parameters. It is cached for
        performance.

        :param parameters_json: A JSON string representing a list of snippet parameters.
        :type parameters_json: str
        :param executor_hosts: A set of hostnames where the snippet can be
            executed. This will be coerced to a frozenset for caching purposes.
        :type executor_hosts: frozenset[str]
        :param add_extra_args_field: Whether to include an extra arguments field in the
            form.
        :type add_extra_args_field: bool
        :param form_action: The action URL for the form submission. Defaults to an
            empty string.
        :type form_action: str
        :param disabled: Whether to disable the form fields and submit button. Defaults
            to `False`.
        :type disabled: bool
        :return: An HTML string representing the form for executing the snippet.
        :rtype: str
        """
        executor_hosts_fieldset = get_executor_hosts_fieldset(executor_hosts)
        executor_hosts_fieldset.disabled = disabled
        fieldsets = [
            executor_hosts_fieldset,
        ]
        parameters = Snippet._get_parameters_from_json(parameters_json).parameters
        logger.debug("Snippet params: %s", parameters)
        fields = []
        for param in parameters:
            try:
                fields.append(param.to_form_field())
            except ValidationError:
                logger.warning("Invalid snippet parameter: %r", param, exc_info=True)
        if add_extra_args_field:
            fields.append(EXTRA_ARGS_INPUT)
        logger.debug("Generated snippet form fields from params: %s", fields)
        if fields:
            fieldsets.append(
                FieldsetElement(legend="Parameters", children=fields, disabled=disabled)
            )
        return FormElement(
            id="snippetExecuteForm",
            children=fieldsets,
            submit_button=SubmitButtonElement(
                label="Execute",
                icon="send",
                classes=("text", "medium"),
                disabled=disabled,
            ),
            action=form_action,
        ).to_html()

    @staticmethod
    @ttl_cache(ttl=_ONE_HOUR, maxsize=16)
    def _get_execution_model(
        parameters_json: str, *, add_extra_args_field: bool
    ) -> type[BaseSnippetArgs]:
        """Generate a Pydantic model for validating snippet execution parameters.

        This internal method creates a dynamic Pydantic model based on the snippet's
        parameters. It is cached for performance.

        :param parameters_json: A JSON string representing a list of snippet parameters.
        :type parameters_json: str
        :param add_extra_args_field: Whether to include an extra arguments field in the
            model.
        :type add_extra_args_field: bool
        :return: A Pydantic model class for validating the snippet's execution
            parameters.
        :rtype: type[BaseSnippetArgs]
        """
        parameters = Snippet._get_parameters_from_json(parameters_json).parameters
        logger.debug("Snippet params: %s", parameters)
        unique_identifiers = generate_unique_identifiers()
        fields = {}
        positional_fields = {}
        for param in parameters:
            field_name = next(unique_identifiers)
            field = (param.validation_type, param.to_validation_field())
            logger.debug(
                "Generated snippet model field from param %s: %s", param, field
            )
            if param.positional:
                positional_fields[field_name] = field
            else:
                fields[field_name] = field
        if add_extra_args_field:
            fields[BaseSnippetArgs.extra_args_field] = (
                ExtraArgsField,
                Field(default_factory=list, alias=EXTRA_ARGS_INPUT_NAME),
            )
        return create_model(
            "SnippetArgs",
            **fields,
            **positional_fields,
            __base__=BaseSnippetArgs,
        )

    @staticmethod
    @ttl_cache(ttl=_ONE_HOUR, maxsize=16)
    def _get_execution_interpreter(snippet_path: Path) -> str | None:
        """Determine the execution interpreter for a snippet path.

        This method checks the snippet's file extension and MIME type against the
        configured list of interpreters in the settings. It returns the most appropriate
        interpreter found, or None if no interpreter matches.

        :param snippet_path: The path to the snippet file.
        :type snippet_path: Path
        :return: The interpreter for executing the snippet, or None if no interpreter is
            found.
        :rtype: str | None
        """
        interpreters = snippets_settings.INTERPRETERS
        snippet_filters = [
            (snippet_path.suffix.lower(), SnippetFilterType.EXTENSION),
            (guess_mime_type(snippet_path), SnippetFilterType.MIME_TYPE),
        ]
        snippet_filters.sort(
            key=lambda f: f in interpreters
            and len(interpreters) - list(interpreters).index(f),
            reverse=True,
        )
        return interpreters.get(snippet_filters[0])

    @classmethod
    async def from_path(cls, path: PathLike, *, update_meta: bool = False) -> Self:
        """Create a new Snippet instance from a file path.

        This method computes the MD5 hash digest of the file at the specified path and
        instantiates a new Snippet with the filename and computed MD5 hash.

        :param path: A path-like object pointing to the snippet file.
        :type path: PathLike
        :param update_meta: Whether to update the snippet's metadata after creation.
            Defaults to False.
        :type update_meta: bool
        :return: A new instance of Snippet with the corresponding filename and
            md5_digest.
        :rtype: Snippet
        """
        path = snippets_settings.SNIPPETS_DIR / Path(path)
        file_hash = hashlib.md5(usedforsecurity=False)
        chunk_size = 8192
        async with aiofiles.open(path, "rb") as f:
            while chunk := await f.read(chunk_size):
                file_hash.update(chunk)
        snippet = cls(
            filename=str(path.relative_to(snippets_settings.SNIPPETS_DIR)),
            md5_digest=file_hash.hexdigest(),
            size=await getsize(path),
        )
        if update_meta:
            await snippet.update_meta()
        return snippet


class SnippetExecutionMeta(BaseModel):
    """Metadata required for executing a snippet.

    :param target: The target hostname where the snippet will be executed.
    :type target: NonEmptyStr
    :param interpreter: The interpreter to use for executing the snippet (e.g., bash,
        python).
    :type interpreter: NonEmptyStr
    :param snippet_source: The URL to the snippet source file.
    :type snippet_source: StrAnyUrl
    :param access_token: The access token for authentication when fetching the snippet.
    :type access_token: NonEmptyStr
    :param md5_checksum: The MD5 checksum of the snippet file to verify integrity.
    :type md5_checksum: str
    :param snippet_filename: The filename of the snippet.
    :type snippet_filename: NonEmptyStr
    :param args: Additional command-line arguments to pass to the snippet during
        execution.
    :type args: NonEmptyStr | None
    """

    target: NonEmptyStr
    interpreter: NonEmptyStr
    snippet_source: StrAnyUrl
    access_token: NonEmptyStr
    snippet_filename: NonEmptyStr = Field(..., serialization_alias="_snippet_filename")
    md5_checksum: str = Field(min_length=32, max_length=32)
    args: NonEmptyStr | EmptyStrToNone = None

    @computed_field
    @property
    def _job_id_prefix(self) -> str:
        """Get a prefix for job IDs based on the snippet filename.

        :return: A string prefix for job IDs.
        :rtype: str
        """
        return self.snippet_filename
