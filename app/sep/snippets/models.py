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

"""Define models for the snippets feature as part of the SEP app."""

import hashlib
import json
import logging
from collections.abc import Iterable
from enum import Enum
from functools import cached_property
from io import SEEK_END
from os import PathLike
from pathlib import Path
from typing import Any, NamedTuple, NotRequired, Self

import aiofiles
import yaml
from aiofiles.ospath import getsize
from async_lru import alru_cache
from pydantic import (
    AliasChoices,
    BaseModel,
    computed_field,
    Field,
    field_validator,
    model_validator,
    PositiveInt,
    validate_call,
    ValidationError,
)
from pydantic.fields import FieldInfo
from pydantic_core.core_schema import ValidationInfo, ValidatorFunctionWrapHandler
from sqlalchemy import Column, JSON
from sqlmodel import Field as SQLField
from typing_extensions import TypedDict

from app.core.db import BaseSQLModel
from app.core.db.models import DateTimeWithTimezone
from app.core.utils import (
    json_serializer,
    run_pydantic_type_validator,
    ttl_cache,
    utc_now,
)
from app.core.utils.fields import EnumFieldMixin, FilePathLike, RequiredStr, UTCDatetime
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.forms import (
    CheckboxInputElement,
    EXTRA_ARGS_INPUT,
    FieldsetElement,
    FormElement,
    FormFieldElement,
    get_executor_hosts_fieldset,
    NumberInputElement,
    SelectElement,
    SubmitButtonElement,
    TextareaElement,
    TextInputElement,
    TextInputHTMLElement,
)

__all__ = ["FilePreview", "Snippet", "SnippetMetaParameter"]

_ONE_HOUR = 60 * 60
logger = logging.getLogger(__name__)

DefaultValueType = str | int | float | bool | None


class SnippetMetaParameterType(EnumFieldMixin, Enum):
    """Enumerate the possible types for snippet parameters."""

    STR = str
    INT = int
    FLOAT = float
    BOOL = bool


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


class SnippetMetaValidatedParameters(NamedTuple):
    """A collection of validated snippet parameters and any validation errors.

    :param parameters: A list of validated snippet parameters.
    :type parameters: list[SnippetMetaParameter]
    :param errors: A list of validation error messages.
    :type errors: list[str]
    """

    parameters: list["SnippetMetaParameter"]
    errors: list[str]


class SnippetMetaParameterChoice(TypedDict):
    """Represent a choice for a snippet parameter.

    :param value: The value of the choice.
    :type value: str
    :param label: The label for the choice. If not provided, the value will be used as
        the label.
    :type label: NotRequired[str]
    """

    value: str
    label: NotRequired[str]


class SnippetMetaParameter(BaseModel):
    """Represent a parameter for a support snippet.

    :param name: The name of the parameter.
    :type name: RequiredStr
    :param py_type: The type of the parameter (`str`, `int`, `float`, `bool`). Defaults
        to `str`. This parameter is validated as "type" in input data.
    :type py_type: SnippetMetaParameterType
    :param required: Whether the parameter is required. Defaults to False.
    :type required: bool
    :param positional: Whether the parameter is positional. Defaults to False.
    :type positional: bool
    :param description: A description of the parameter. Defaults to None, meaning it
        won't be used for validation.
    :type description: RequiredStr | None
    :param label: A label for the parameter. Defaults to None, meaning it won't be used
        for validation.
    :type label: RequiredStr | None
    :param placeholder: A placeholder for the parameter. Defaults to None, meaning it
        won't be used for validation.
    :type placeholder: RequiredStr | None
    :param default: The default value for the parameter. Defaults to None, meaning no
        default.
    :type default: str | int | float | bool | None
    :param choices: A list of choices for the parameter. Each choice can be a string or
        a dictionary with "label" and "value" keys. Defaults to None, meaning it won't
        be used for validation. This parameter is validated as "options" or "choices"
        in input data.
    :type choices: list[str | SnippetMetaParameterChoice] | None
    :param min_length: The minimum length for string parameters. Defaults to None,
        meaning it won't be used for validation.
    :type min_length: int | None
    :param max_length: The maximum length for string parameters. Defaults to None,
        meaning it won't be used for validation.
    :type max_length: int | None
    :param pattern: A regex pattern that the parameter value must match. Defaults to
        None, meaning it won't be used for validation.
    :type pattern: RequiredStr | None
    :param gt: The value must be greater than this for numeric parameters. Defaults to
        None, meaning it won't be used for validation.
    :type gt: float | None
    :param lt: The value must be less than this for numeric parameters. Defaults to
        None, meaning it won't be used for validation.
    :type lt: float | None
    :param ge: The value must be greater than or equal to this for numeric parameters.
        Defaults to None, meaning it won't be used for validation.
    :type ge: float | None
    :param le: The value must be less than or equal to this for numeric parameters.
        Defaults to None, meaning it won't be used for validation.
    :type le: float | None
    :param step: The step value for numeric parameters. Defaults to None, which sets
        step to 1 for int and 0.1 for float types.
    :type step: float | None
    :param html_elem: The HTML element to use for text input parameters. Can be
        TextInputHTMLElement.TEXT or TextInputHTMLElement.TEXTAREA. Defaults to None,
        which uses TextInputHTMLElement.TEXT.
    :type html_elem: TextInputHTMLElement | None
    """

    name: RequiredStr = Field(..., serialization_alias="title")
    py_type: SnippetMetaParameterType = Field(
        SnippetMetaParameterType.STR, validation_alias="type"
    )
    required: bool = False
    positional: bool = False
    description: RequiredStr | None = None
    label: RequiredStr | None = None
    placeholder: RequiredStr | None = None
    default: DefaultValueType = None
    choices: list[str | SnippetMetaParameterChoice] | None = Field(
        None, validation_alias=AliasChoices("choices", "options")
    )
    min_length: int | None = None
    max_length: int | None = None
    pattern: RequiredStr | None = None
    gt: float | None = None
    lt: float | None = None
    ge: float | None = None
    le: float | None = None
    step: float | None = None
    html_elem: TextInputHTMLElement | None = None

    @model_validator(mode="after")
    def set_default_step(self) -> Self:
        """Set default step for numeric parameters if not provided.

        :return: The instance of SnippetMetaParameter with the step set if it is a
            numeric type.
        :rtype: SnippetMetaParameter
        """
        if self.step is None:
            if self.py_type == SnippetMetaParameterType.FLOAT:
                self.step = 0.1
            elif self.py_type == SnippetMetaParameterType.INT:
                self.step = 1.0
        return self

    @field_validator("py_type", mode="wrap")
    @classmethod
    def set_default_type_if_unknown(
        cls, value: Any, handler: ValidatorFunctionWrapHandler
    ) -> SnippetMetaParameterType:
        """Set default type to str if the provided type is unknown.

        :param value: The input value to validate.
        :type value: Any
        :param handler: The validation handler function.
        :type handler: ValidatorFunctionWrapHandler
        :return: The validated type, defaulting to str if unknown.
        :rtype: SnippetMetaParameterType
        """
        try:
            return handler(value)
        except ValidationError:
            logger.debug(
                "Unknown type %s for snippet parameter, defaulting to str", value
            )
            return SnippetMetaParameterType.STR

    @field_validator("default")
    @classmethod
    def validate_default(
        cls, value: DefaultValueType, info: ValidationInfo
    ) -> DefaultValueType:
        """Validate the default value against the parameter type.

        :param value: The default value to validate.
        :type value: DefaultValueType
        :param info: The validation information.
        :type info: ValidationInfo
        :return: The validated default value.
        :rtype: DefaultValueType
        """
        if value is None:
            return value
        param_type = info.data["py_type"]
        return run_pydantic_type_validator(param_type.value, value)

    @property
    def form_field_element_cls(self) -> type[FormFieldElement]:
        """Get the form field element class based on the parameter type.

        :return: The appropriate form field element class for the parameter type.
        :rtype: type[FormFieldElement]
        """
        if self.choices:
            return SelectElement
        if self.py_type == SnippetMetaParameterType.BOOL:
            return CheckboxInputElement
        if self.py_type in [
            SnippetMetaParameterType.INT,
            SnippetMetaParameterType.FLOAT,
        ]:
            return NumberInputElement
        if self.html_elem == TextInputHTMLElement.TEXTAREA:
            return TextareaElement
        return TextInputElement

    def to_field(self) -> FieldInfo:
        """Convert the SnippetMetaParameter to a Pydantic Field.

        :return: A Pydantic Field instance with the attributes of the parameter.
        :rtype: FieldInfo
        """
        attrs = self.model_dump(
            include={
                "name",
                "description",
                "default",
                "min_length",
                "max_length",
                "pattern",
                "gt",
                "lt",
                "ge",
                "le",
            },
            by_alias=True,
            exclude_none=True,
        )
        return Field(**attrs, validate_default=True)

    def to_form_field(self) -> FormFieldElement:
        """Convert the SnippetMetaParameter to a form field element.

        :return: An instance of the form field element class corresponding to the
            parameter type, populated with the parameter's attributes.
        :rtype: FormFieldElement
        """
        instance_data = self.model_dump(exclude_none=True)
        return self.form_field_element_cls.model_validate(instance_data)


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

    def get_validated_parameters(self) -> SnippetMetaValidatedParameters:
        """Get the validated parameters of the snippet.

        :return: A SnippetMetaValidatedParameters instance containing the list of valid
            parameters and any validation errors encountered.
        :rtype: SnippetMetaValidatedParameters
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
            add_extra_field=not self.meta.get(
                "strict", snippets_settings.META.DEFAULT_STRICT
            ),
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
    ) -> SnippetMetaValidatedParameters:
        """Parse and validate snippet parameters from a JSON string.

        :param parameters_json: A JSON string representing a list of snippet parameters.
        :type parameters_json: str
        :return: A SnippetMetaValidatedParameters instance containing the list of valid
            parameters and any validation errors encountered.
        :rtype: SnippetMetaValidatedParameters
        """
        parameters = json.loads(parameters_json) or []
        if not isinstance(parameters, list):
            error_msg = f"Invalid snippet parameters, expected a list but got {parameters.__class__.__name__}"
            logger.warning("%s: %r", error_msg, parameters)
            return SnippetMetaValidatedParameters(parameters=[], errors=[error_msg])
        valid_parameters = []
        errors = []
        param_preview_max_size = 100
        for param in parameters:
            try:
                valid_parameters.append(SnippetMetaParameter.model_validate(param))
            except ValidationError:
                error_msg = "Invalid snippet parameter"
                param_preview = repr(param)
                logger.warning("%s: %s", error_msg, param_preview, exc_info=True)
                if len(param_preview) > param_preview_max_size:
                    param_preview = f"{param_preview[:param_preview_max_size]}..."
                errors.append(f"{error_msg}: {param_preview}")
        return SnippetMetaValidatedParameters(
            parameters=valid_parameters, errors=errors
        )

    @staticmethod
    @validate_call
    @ttl_cache(ttl=_ONE_HOUR, maxsize=16)
    def _to_form(
        parameters_json: str, executor_hosts: frozenset[str], *, add_extra_field: bool
    ) -> str:
        fieldsets = [
            get_executor_hosts_fieldset(executor_hosts),
        ]
        parameters = Snippet._get_parameters_from_json(parameters_json).parameters
        logger.debug("Snippet params: %s", parameters)
        fields = []
        for param in parameters:
            try:
                fields.append(param.to_form_field())
            except ValidationError:
                logger.warning("Invalid snippet parameter: %r", param, exc_info=True)
        if add_extra_field:
            fields.append(EXTRA_ARGS_INPUT)
        logger.debug("Generated snippet form fields from params: %s", fields)
        if fields:
            fieldsets.append(FieldsetElement(legend="Parameters", children=fields))
        return FormElement(
            id="snippetExecuteForm",
            children=fieldsets,
            submit_button=SubmitButtonElement(
                label="Execute", icon="send", classes=("text", "medium")
            ),
        ).to_html()

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
