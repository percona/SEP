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

"""Define models for snippet metadata in the SEP app."""

__all__ = [
    "SnippetMetaParameter",
    "SnippetMetaParameterChoice",
    "SnippetMetaParameterType",
    "SnippetMetaParametersValidationResult",
]

import logging
from enum import Enum, StrEnum
from functools import cached_property
from string import Template
from typing import Annotated, Any, NamedTuple, NotRequired, Self

from annotated_types import (
    GroupedMetadata,
    Interval,
)
from pydantic import (
    AliasChoices,
    BaseModel,
    computed_field,
    Field,
    field_validator,
    model_validator,
    PositiveInt,
    StringConstraints,
    ValidationError,
)
from pydantic.fields import FieldInfo
from pydantic_core.core_schema import ValidationInfo, ValidatorFunctionWrapHandler
from typing_extensions import TypedDict

from app.core.utils import run_pydantic_type_validator, shorten_text
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, NonEmptyStr
from app.core.utils.pydantic import (
    field_with_metadata,
    loc_to_dot_sep,
)
from app.sep.snippets.forms import (
    CheckboxInputElement,
    FormFieldElement,
    NumberInputElement,
    SelectElement,
    TextareaElement,
    TextInputElement,
    TextInputHTMLElement,
)

ParameterType = str | int | float | bool | None

logger = logging.getLogger(__name__)


class SnippetMetaParameterType(EnumFieldMixin, Enum):
    """Enumerate the possible types for snippet parameters."""

    STR = str
    INT = int
    FLOAT = float
    BOOL = bool


class SnippetMetaParametersValidationResult(NamedTuple):
    """A collection of validated snippet parameters and any validation errors.

    :param parameters: A list of validated snippet parameters.
    :type parameters: list[app.sep.snippets.meta.SnippetMetaParameter]
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
    :type name: NonEmptyStr
    :param py_type: The type of the parameter (`str`, `int`, `float`, `bool`). Defaults
        to `str`. This parameter is validated as "type" in input data.
    :type py_type: SnippetMetaParameterType
    :param required: Whether the parameter is required. Defaults to False.
    :type required: bool
    :param positional: Whether the parameter is positional. Defaults to False.
    :type positional: bool
    :param arg_format: The format string for the parameter when used as a command-line
        argument. Use `${value}` as a placeholder (required for non-flag arguments).
        Defaults to None, which uses the default format from the snippets settings.
    :type arg_format: NonEmptyStr | None
    :param description: A description of the parameter. Defaults to None, meaning it
        won't be used for validation.
    :type description: NonEmptyStr | None
    :param label: A label for the parameter. Defaults to None, meaning it won't be used
        for validation.
    :type label: NonEmptyStr | None
    :param placeholder: A placeholder for the parameter. Defaults to None, meaning it
        won't be used for validation.
    :type placeholder: NonEmptyStr | None
    :param default: The default value for the parameter. Defaults to None, meaning no
        default.
    :type default: str | int | float | bool | None
    :param choices: A list of choices for the parameter. Each choice can be a string or
        a dictionary with "label" and "value" keys. Defaults to None, meaning it won't
        be used for validation. This parameter is validated as "options" or "choices"
        in input data.
    :type choices: list[SnippetMetaParameterChoice] | None
    :param min_length: The minimum length for string parameters. Defaults to 1.
    :type min_length: PositiveInt | None
    :param max_length: The maximum length for string parameters. Defaults to 1,
        meaning it won't be used for validation.
    :type max_length: PositiveInt | None
    :param pattern: A regex pattern that the parameter value must match. Defaults to
        None, meaning it won't be used for validation.
    :type pattern: NonEmptyStr | None
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

    name: NonEmptyStr = Field(
        ..., pattern=r"^\w(?:[\w-]+\w)?\w*$", serialization_alias="title"
    )
    py_type: SnippetMetaParameterType = Field(
        SnippetMetaParameterType.STR, validation_alias="type"
    )
    required: bool = False
    positional: bool = False
    arg_format: NonEmptyStr | None = None
    description: NonEmptyStr | None = None
    label: NonEmptyStr | None = None
    placeholder: NonEmptyStr | None = None
    default: ParameterType = None
    choices: list[SnippetMetaParameterChoice] | None = Field(
        None, validation_alias=AliasChoices("choices", "options")
    )
    min_length: PositiveInt = 1
    max_length: PositiveInt | None = None
    pattern: NonEmptyStr | None = None
    gt: ParameterType = None
    lt: ParameterType = None
    ge: ParameterType = None
    le: ParameterType = None
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

    @model_validator(mode="after")
    def validate_arg_format(self) -> Self:
        """Validate the arg_format for non-flag parameters contains '${value}'.

        :return: The validated `SnippetMetaParameter` instance.
        :rtype: SnippetMetaParameter
        :raises ValueError: If arg_format is provided for non-flag parameters but
            does not include '${value}'.
        """
        if (
            not self.is_flag
            and self.arg_format is not None
            and "value" not in Template(self.arg_format).get_identifiers()
        ):
            raise ValueError(
                "arg_format must include '${value}' for non-flag parameters"
            )
        return self

    @field_validator("choices", mode="before")
    @classmethod
    def normalize_choices(cls, value: Any) -> Any:
        """Normalize choices to a list of dictionaries with 'value'.

        :param value: The input value to normalize.
        :type value: Any
        :return: The normalized list of choices or the original input value.
        :rtype: Any
        """
        if isinstance(value, list):
            return [
                {"value": choice} if isinstance(choice, str) else choice
                for choice in value
            ]
        return value

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

    @field_validator("default", "gt", "lt", "ge", "le")
    @classmethod
    def coerce_to_type(
        cls, value: ParameterType, info: ValidationInfo
    ) -> ParameterType:
        """Validate and coerce the value to the specified parameter type.

        :param value: The value to validate.
        :type value: ParameterType
        :param info: The validation information.
        :type info: ValidationInfo
        :return: The validated default value.
        :rtype: ParameterType
        """
        if value is None:
            return value
        param_type = info.data["py_type"]
        return run_pydantic_type_validator(param_type.value, value)

    @computed_field
    @cached_property
    def is_flag(self) -> bool:
        """Determine if the parameter is a boolean flag.

        :return: True if the parameter is of type BOOL, else False.
        :rtype: bool
        """
        return self.py_type == SnippetMetaParameterType.BOOL

    @cached_property
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

    @cached_property
    def constraints(self) -> list[GroupedMetadata]:
        """Get the constraints for the parameter based on its type and attributes.

        :return: A list of constraint metadata instances applicable to the parameter.
        :rtype: list[GroupedMetadata]
        """
        constraints = []
        if self.py_type == SnippetMetaParameterType.STR:
            constraints.append(
                StringConstraints(
                    **self.model_dump(
                        include={"min_length", "max_length", "pattern"},
                        exclude_none=True,
                    )
                )
            )
        interval_constraints = self.model_dump(
            include={"gt", "lt", "ge", "le"}, exclude_none=True
        )
        if interval_constraints:
            constraints.append(Interval(**interval_constraints))
        return constraints

    @cached_property
    def validation_type(
        self,
    ) -> type:
        """Get the validation type for the parameter.

        :return: The type to use for validating the parameter value.
        :rtype: type
        """
        if self.choices:
            raw_type = StrEnum(
                "ParamChoices", [choice["value"] for choice in self.choices]
            )
        else:
            raw_type = self.py_type.value
            if self.constraints:
                raw_type = Annotated[raw_type, *self.constraints]
        if not self.required and self.default is None:
            return raw_type | EmptyStrToNone
        return raw_type

    def to_validation_field(self) -> FieldInfo:
        """Convert the SnippetMetaParameter to a Pydantic Field.

        :return: A Pydantic Field instance with the attributes of the parameter.
        :rtype: FieldInfo
        """
        attrs = self.model_dump(
            include={
                "name",
                "description",
                "default",
            },
            by_alias=True,
            exclude_none=True,
        )
        if not self.required and self.default is None:
            attrs["default"] = None
        return field_with_metadata(
            **attrs,
            alias=self.name,
            metadata=self.model_dump(
                include={"positional", "is_flag", "arg_format"},
                exclude_none=True,
                exclude_defaults=True,
            ),
        )

    def to_form_field(self) -> FormFieldElement:
        """Convert the SnippetMetaParameter to a form field element.

        :return: An instance of the form field element class corresponding to the
            parameter type, populated with the parameter's attributes.
        :rtype: FormFieldElement
        """
        instance_data = self.model_dump(exclude_none=True)
        return self.form_field_element_cls.model_validate(instance_data)

    @staticmethod
    def convert_validation_errors(exc: ValidationError, input_param: Any) -> list[str]:
        """Convert Pydantic ValidationError to a list of readable error messages.

        :param exc: The ValidationError instance to convert.
        :type exc: ValidationError
        :param input_param: The input parameter that caused the validation error.
        :type input_param: Any
        :return: A list of formatted error messages.
        :rtype: list[str]
        """
        errors = []
        base_error_msg = "Parameter error"
        if isinstance(input_param, dict) and "name" in input_param:
            param_preview = repr(input_param["name"])
        else:
            param_preview = repr(input_param)
        param_preview = shorten_text(param_preview, keep_last_chars=1)
        for param_error in exc.errors():
            param_error_loc = loc_to_dot_sep(param_error.get("loc", ()))
            param_error_msg = param_error.get("msg")
            error_msg = f"{base_error_msg} ({param_preview})"
            if param_error_loc:
                error_msg += f" at {param_error_loc!r}"
            if param_error_msg:
                error_msg += f": {param_error_msg}"
            errors.append(error_msg)
        return errors
