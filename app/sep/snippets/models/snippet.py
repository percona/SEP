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

__all__ = ["FilePreview", "Snippet"]

import hashlib
import json
import logging
import shlex
from collections.abc import Iterable
from functools import cached_property
from io import SEEK_END
from os import PathLike
from pathlib import Path
from typing import Annotated, Any, NamedTuple, Self

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
from app.core.utils.fields import FilePathLike, UTCDatetime
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.forms import (
    EXTRA_ARGS_INPUT,
    FieldsetElement,
    FormElement,
    get_executor_hosts_fieldset,
    SubmitButtonElement,
)
from app.sep.snippets.models.meta import (
    SnippetMetaParameter,
    SnippetMetaParametersValidationResult,
)
from app.sep.snippets.utils import generate_unique_identifiers

_ONE_HOUR = 60 * 60
logger = logging.getLogger(__name__)

ExtraArgsField = Annotated[list[str], BeforeValidator(shlex.split)]


class FilePreview(NamedTuple):
    """A preview of a snippet's content.

    :param content: A preview of the snippet's content, limited to a certain number of
        characters and lines.
    :type content: str
    :param is_truncated: Whether the preview content is truncated (i.e., if the full content
        exceeds the preview limits).
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

        :return: `True` if extra arguments are allowed, else `False`. Defaults to the value
            specified in the snippets settings if not explicitly set in the metadata.
        :rtype: bool
        """
        return self.meta.get(
            "allow_extra_args", snippets_settings.META.DEFAULT_ALLOW_EXTRA_ARGS
        )

    @property
    def can_execute(self) -> bool:
        """Determine whether the snippet can be executed.

        A snippet can be executed if it is approved and either parameter errors are
        ignored in the settings or there are no validation errors in the parameters.

        :return: `True` if the snippet can be executed, else `False`.
        :rtype: bool
        """
        return self.is_approved and (
            snippets_settings.META.IGNORE_INVALID_PARAMETERS
            or not self.validated_parameters.errors
        )

    @cached_property
    def validated_parameters(self) -> SnippetMetaParametersValidationResult:
        """Get the validated parameters of the snippet.

        :return: A `SnippetMetaParametersValidationResult` instance containing the list of valid
            parameters and any validation errors encountered.
        :rtype: SnippetMetaParametersValidationResult
        """
        parameters = self.meta.get("parameters", [])
        return self._get_parameters_from_json(
            json_serializer(parameters, sort_keys=True),
        )

    async def get_preview(self) -> FilePreview:
        """Get a preview of the snippet code.

        :return: A :class:`FilePreview` instance containing a preview of the snippet code.
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

    def to_form(self, executor_hosts: Iterable[str]) -> str:
        """Generate an HTML form for executing the snippet.

        This method creates a form with fields based on the snippet's metadata and
        the provided executor hosts. It includes a select element for choosing the
        executor host and fields for snippet parameters.

        :param executor_hosts: An iterable  of hostnames where the snippet can be
            executed.
        :type executor_hosts: Iterable[str]
        :return: An HTML string representing the form for executing the snippet.
        :rtype: str
        """
        parameters = self.meta.get("parameters", [])
        logger.debug("Meta Snippet parameters: %s)", parameters)
        return self._to_form(
            json_serializer(parameters, sort_keys=True),
            executor_hosts,
            add_extra_args_field=self.allow_extra_args,
            disabled=not self.can_execute,
        )

    def get_execution_model(self) -> type[BaseModel]:
        """Generate a Pydantic model for validating snippet execution parameters.

        This method creates a dynamic Pydantic model based on the snippet's metadata,
        which can be used to validate the parameters required for executing the snippet.

        :return: A Pydantic model class for validating the snippet's execution
            parameters.
        :rtype: type[BaseModel]
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
        :return: A SnippetMetaParametersValidationResult instance containing the list of valid
            parameters and any validation errors encountered.
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
        disabled: bool = False,
    ) -> str:
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
        ).to_html()

    @staticmethod
    @ttl_cache(ttl=_ONE_HOUR, maxsize=16)
    def _get_execution_model(
        parameters_json: str, *, add_extra_args_field: bool
    ) -> type[BaseModel]:
        parameters = Snippet._get_parameters_from_json(parameters_json).parameters
        logger.debug("Snippet params: %s", parameters)
        unique_identifiers = generate_unique_identifiers()
        fields = {}
        positional_fields = {}
        for param in parameters:
            field_name = next(unique_identifiers)
            field = (param.validation_type, param.to_validation_field())
            if param.positional:
                positional_fields[field_name] = field
            else:
                fields[field_name] = field
        if add_extra_args_field:
            fields["extra_args"] = (
                ExtraArgsField,
                Field(None, alias=EXTRA_ARGS_INPUT.name),
            )
        logger.debug("Generated snippet model fields from params: %s", fields)
        return create_model("DynamicSnippetExecution", **fields, **positional_fields)

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
