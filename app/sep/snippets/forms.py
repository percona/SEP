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

"""Define HTML elements and form components using Pydantic models."""

from abc import ABC, abstractmethod
from enum import auto, StrEnum
from functools import cached_property
from html import escape as html_escape
from typing import Annotated, Any, ClassVar

from pydantic import (
    AliasChoices,
    BaseModel,
    computed_field,
    ConfigDict,
    Field,
    model_validator,
    PositiveInt,
    validate_call,
)

from app.core.utils import ttl_cache
from app.core.utils.fields import EnumFieldMixin, RequiredStr, UniqueTuple

HTMLClassName = Annotated[str, Field(pattern=r"^-?[_a-zA-Z]+[_a-zA-Z0-9-]*$")]
_TWENTY_FOUR_HOURS = 24 * 60 * 60
_SEVEN_DAYS = 7 * _TWENTY_FOUR_HOURS


class TextInputHTMLElement(EnumFieldMixin, StrEnum):
    """Enumerate the types of HTML text input elements."""

    INPUT = auto()
    TEXTAREA = auto()


class InputType(StrEnum):
    """Enumerate the types of HTML input elements."""

    TEXT = "text"
    NUMBER = "number"
    CHECKBOX = "checkbox"


class FormMethod(StrEnum):
    """Enumerate the possible methods used in HTML forms."""

    GET = "get"
    POST = "post"
    DIALOG = "dialog"


class BaseHTMLEntity(BaseModel, ABC):
    """Define base class for HTML entities.

    This class defines the interface for HTML entities that can be converted to HTML.
    It requires subclasses to implement the `to_html` method, which should return
    the HTML representation of the entity.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    @abstractmethod
    def to_html(self) -> str:
        """Return HTML representation of entity.

        :return: The HTML representation of the entity as a string.
        :rtype: str
        """


class BaseHTMLElement(BaseHTMLEntity, ABC):
    """Define base class for HTML elements.

    This class provides common attributes and methods for HTML elements, including
    handling of tag names, classes, IDs, titles, and HTML attributes. It also
    provides methods for generating start and end tags, as well as converting the
    element to HTML.

    :cvar: TAG_NAME: The name of the HTML tag (e.g., 'div', 'span').
    :vartype: TAG_NAME: ClassVar[str]
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueTuple[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    """

    TAG_NAME: ClassVar[str]
    classes: UniqueTuple[HTMLClassName] = Field(default_factory=tuple, exclude=True)
    id: RequiredStr | None = Field(None, pattern=r"^\S+$")
    title: RequiredStr | None = Field(None, validation_alias="description")

    @computed_field(alias="class")
    @property
    def _class(self) -> str | None:
        """Return the class attribute as a space-separated string of class names.

        :return: A space-separated string of class names or None if no classes are set.
        :rtype: str | None
        """
        return " ".join(self.classes) or None

    @cached_property
    def attributes(self) -> str:
        """Return a string of HTML attributes from the model fields.

        :return: A string of HTML attributes.
        :rtype: str
        """
        return self._get_attributes_str(
            sorted(self.model_dump(by_alias=True, exclude_none=True).items())
        )

    @cached_property
    def start_tag(self) -> str:
        """Return the opening tag for the HTML element.

        :return: The opening tag as a string.
        :rtype: str
        """
        tag = f"<{self.TAG_NAME}"
        attrs = self.attributes
        if attrs:
            tag += f" {attrs}"
        tag += ">"
        return tag

    @property
    def prepend_raw(self) -> str:
        """Return any raw HTML to prepend before the start tag.

        This can be overridden in subclasses to add custom HTML before the element's
        start tag.

        :return: An empty string by default.
        :rtype: str
        """
        return ""

    @property
    def append_raw(self) -> str:
        """Return any raw HTML to append after the end tag.

        This can be overridden in subclasses to add custom HTML after the element's
        end tag.

        :return: An empty string by default.
        :rtype: str
        """
        return ""

    @staticmethod
    @validate_call
    @ttl_cache(ttl=_TWENTY_FOUR_HOURS, maxsize=64)
    def _get_attributes_str(attributes: tuple[tuple[str, Any], ...]) -> str:
        """Convert a list of attribute-value pairs into a string of HTML attributes.

        :param attributes: A tuple of (attribute, value) pairs.
        :type attributes: tuple[tuple[str, Any], ...]
        :return: A string of HTML attributes.
        :rtype: str
        """
        attrs = []
        for attr, value in attributes:
            if isinstance(value, bool):
                if value:
                    attrs.append(attr)
            else:
                attrs.append(f'{attr}="{html_escape(str(value))}"')
        return " ".join(attrs)


class VoidHTMLElement(BaseHTMLElement, ABC):
    """Define base class for void HTML elements (self-closing tags).

    This class provides the interface for HTML elements that do not have closing tags,
    such as `<input>`.

    :cvar: TAG_NAME: The name of the HTML tag (e.g., 'div', 'span').
    :vartype: TAG_NAME: ClassVar[str]
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    """

    def to_html(self) -> str:
        """Return the HTML representation of the void element.

        :return: The HTML representation of the void element.
        :rtype: str
        """
        return self.prepend_raw + self.start_tag + self.append_raw


class HTMLElement(BaseHTMLElement, ABC):
    """Define base class for HTML elements that can have children.

    This class provides methods for handling child elements and generating the full
    HTML representation of the element, including its children.

    :cvar: TAG_NAME: The name of the HTML tag (e.g., 'div', 'span').
    :vartype: TAG_NAME: ClassVar[str]
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    :param: children: A tuple of child HTML entities contained within this element.
    :type: children: tuple[BaseHTMLEntity, ...]
    """

    children: tuple[BaseHTMLEntity, ...] = Field(default_factory=tuple, exclude=True)

    @cached_property
    def end_tag(self) -> str:
        """Return the closing tag for the HTML element.

        :return: The closing tag as a string.
        :rtype: str
        """
        return f"</{self.TAG_NAME}>"

    @cached_property
    def inner_html(self) -> str:
        """Return the inner HTML content of the element, including its children.

        This property generates the HTML for all child elements contained within this
        element by calling their `to_html` methods and concatenating the results.

        :return: The inner HTML content as a string.
        :rtype: str
        """
        return "".join(elem.to_html() for elem in self.children)

    def to_html(self) -> str:
        """Return the full HTML representation of the element.

        This method combines the start tag, inner HTML, and end tag, along with any
        raw HTML to prepend or append, to produce the complete HTML for the element.

        :return: The full HTML representation of the element.
        :rtype: str
        """
        return (
            self.prepend_raw
            + self.start_tag
            + self.inner_html
            + self.end_tag
            + self.append_raw
        )


class TextContent(BaseHTMLEntity):
    """Define a simple text content entity.

    This class represents plain text content that can be included within HTML elements.

    :param: text: The text content to be rendered.
    :type: text: str
    """

    text: str

    @model_validator(mode="before")
    @classmethod
    def create_from_str(cls, data: Any) -> Any:
        """Create a TextContent instance from a string.

        Converts a string into a `TextContent` instance, allowing it to be used as
        a child of HTML elements.

        :param data: The input data containing the text content.
        :type data: Any
        :return: The validated data.
        :rtype: Any
        """
        if isinstance(data, str):
            return cls(text=data)
        return data

    def to_html(self) -> str:
        """Return the HTML representation of the text content.

        This method escapes the text content to ensure it is safe for inclusion in HTML,
        preventing issues such as XSS attacks or HTML injection.

        :return: The HTML representation of the text content.
        :rtype: str
        """
        return html_escape(self.text)


class FieldsetElement(HTMLElement):
    """Define a fieldset HTML element with an optional legend.

    This class represents a `<fieldset>` element, which can contain a legend and other
    HTML elements. The legend is typically used to provide a caption for the fieldset.

    :cvar: TAG_NAME: The name of the HTML tag ('fieldset').
    :vartype: TAG_NAME: ClassVar[str]
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    :param: children: A tuple of child HTML entities contained within this element.
    :type: children: tuple[BaseHTMLEntity, ...]
    :param: legend: The text for the legend of the fieldset, if any. Defaults to None.
    :type: legend: RequiredStr | None
    """

    TAG_NAME: ClassVar[str] = "fieldset"
    legend: RequiredStr | None = Field(None, exclude=True)

    @cached_property
    def inner_html(self) -> str:
        """Return the inner HTML content of the fieldset, including the legend if set.

        This property generates the HTML for the legend (if provided) and concatenates
        it with the inner HTML of the fieldset's children.

        :return: The inner HTML content as a string, including the legend if present.
        :rtype: str
        """
        html = super().inner_html
        if self.legend:
            html = f"<legend>{html_escape(self.legend)}</legend>{html}"
        return html


class FormFieldMixin(BaseModel):
    """Mixin for form fields to provide common attributes and methods.

    This mixin provides common attributes and methods for form fields, including
    handling of required fields, labels, and HTML conversion. It is intended to be
    used as a base class for various form field types, such as text inputs, checkboxes,
    and selects.

    :param: name: The name attribute of the form field.
    :type: name: RequiredStr
    :param: required: Whether the field is required. Defaults to False.
    :type: required: bool
    :param: label: The label for the form field, if any. Defaults to None.
    :type: label: RequiredStr | None
    """

    name: RequiredStr
    required: bool = False
    label: RequiredStr | None = Field(None, exclude=True)

    def to_html(self) -> str:
        """Return the HTML representation of the form field.

        This method generates the HTML for the form field, wrapping it in a label if
        a label is provided.

        :return: The HTML representation of the form field, possibly wrapped in a label.
        :rtype: str
        """
        html = super().to_html()
        if self.label:
            return f"<label><span>{html_escape(self.label)}</span>{html}</label>"
        return html


class TypeableFieldMixin(FormFieldMixin):
    """Define mixin for form fields that can have a placeholder attribute.

    :param: name: The name attribute of the form field.
    :type: name: RequiredStr
    :param: required: Whether the field is required. Defaults to False
    :type: required: bool
    :param: label: The label for the form field, if any. Defaults to None
    :type: label: RequiredStr | None
    :param: placeholder: The placeholder text for the form field, if any. Defaults to
        None.
    :type: placeholder: RequiredStr | None
    """

    placeholder: RequiredStr | None = None


class TextFieldMixin(TypeableFieldMixin):
    """Define mixin for text form fields with length validation.

    :param: name: The name attribute of the form field.
    :type: name: RequiredStr
    :param: required: Whether the field is required. Defaults to False
    :type: required: bool
    :param: label: The label for the form field, if any. Defaults to None
    :type: label: RequiredStr | None
    :param: placeholder: The placeholder text for the form field, if any. Defaults to
        None.
    :type: placeholder: RequiredStr | None
    :param: maxlength: The maximum length of the text input. If None, no maximum
        length is enforced. Defaults to None.
    :type: maxlength: PositiveInt | None
    :param: minlength: The minimum length of the text input. If None, no minimum
        length is enforced. Defaults to None.
    :type: minlength: PositiveInt | None
    """

    maxlength: PositiveInt | None = Field(
        None, validation_alias=AliasChoices("maxlength", "max_length")
    )
    minlength: PositiveInt | None = Field(
        None, validation_alias=AliasChoices("minlength", "min_length")
    )


class SetChildrenByLabelMixin(BaseModel):
    """Mixin to set children based on a label.

    This mixin is used to automatically create a child TextContent element
    with the label text after the model is validated. It is useful for elements
    that need to display a label as their content, such as buttons or span elements.

    :param: label: The label text to be used for the child TextContent element.
    :type: label: RequiredStr
    """

    label: RequiredStr = Field(exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _set_children_by_label(cls, data: Any) -> Any:
        if isinstance(data, str):
            data = {"label": data}
        if isinstance(data, dict) and "label" in data:
            data["children"] = (TextContent(text=data["label"]),)
        return data


class SpanElement(SetChildrenByLabelMixin, HTMLElement):
    """Define a span HTML element.

    :cvar: TAG_NAME: The name of the HTML tag ('span').
    :vartype: TAG_NAME: ClassVar[str]
    :param: label: The label text to be used for the child TextContent element.
    :type: label: RequiredStr
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    :param: children: A tuple of child HTML entities contained within this element.
    :type: children: tuple[BaseHTMLEntity, ...]
    """

    TAG_NAME: ClassVar[str] = "span"


class TextareaElement(TextFieldMixin, HTMLElement):
    """Define a textarea HTML element with optional rows and columns.

    :cvar: TAG_NAME: The name of the HTML tag ('textarea').
    :vartype: TAG_NAME: ClassVar[str]
    :param: name: The name attribute of the form field.
    :type: name: RequiredStr
    :param: required: Whether the field is required. Defaults to False
    :type: required: bool
    :param: label: The label for the form field, if any. Defaults to None
    :type: label: RequiredStr | None
    :param: placeholder: The placeholder text for the form field, if any. Defaults to
        None.
    :type: placeholder: RequiredStr | None
    :param: maxlength: The maximum length of the text input. If None, no maximum
        length is enforced. Defaults to None.
    :type: maxlength: PositiveInt | None
    :param: minlength: The minimum length of the text input. If None, no minimum
        length is enforced. Defaults to None.
    :type: minlength: PositiveInt | None
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    :param: children: A tuple of child HTML entities contained within this element.
    :type: children: tuple[BaseHTMLEntity, ...]
    :param: rows: The number of rows in the textarea. If None, no specific
        number of rows is set. Defaults to None.
    :type: rows: PositiveInt | None
    :param: cols: The number of columns in the textarea. If None, no specific
        number of columns is set. Defaults to None.
    :type: cols: PositiveInt | None
    """

    TAG_NAME: ClassVar[str] = "textarea"
    rows: PositiveInt | None = None
    cols: PositiveInt | None = None


class OptionElement(SetChildrenByLabelMixin, HTMLElement):
    """Define an option HTML element.

    :cvar: TAG_NAME: The name of the HTML tag ('option').
    :vartype: TAG_NAME: ClassVar[str]
    :param: label: The label text to be used for the child TextContent element.
    :type: label: RequiredStr
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    :param: children: A tuple of child HTML entities contained within this element.
    :type: children: tuple[BaseHTMLEntity, ...]
    :param: value: The value of the option element, which is submitted with the form.
    :type: value: str
    :param: selected: Whether the option is selected by default. Defaults to False.
    :type: selected: bool
    """

    TAG_NAME: ClassVar[str] = "option"
    value: str
    selected: bool = False

    @model_validator(mode="before")
    @classmethod
    def create_from_str(cls, data: Any) -> Any:
        """Create an OptionElement instance from a string.

        Converts a string into an `OptionElement` instance, allowing it to be used as
        an option in a select element.

        :param data: The input data.
        :type data: Any
        :return: The validated data.
        :rtype: Any
        """
        if isinstance(data, str):
            return {"value": data, "label": data}
        return data

    @model_validator(mode="before")
    @classmethod
    def set_default_label(cls, data: Any) -> Any:
        """Set the label for the option element if not provided.

        If the input data is a dictionary and contains a "value" key, it sets the
        "label" key to the value of "value" if "label" is not already set.

        :param data: The input data.
        :type data: Any
        :return: The validated data with the label set.
        :rtype: Any
        """
        if isinstance(data, dict) and "value" in data:
            data["label"] = data.get("label", data["value"])
        return data


class SelectElement(FormFieldMixin, HTMLElement):
    """Define a select HTML element with options.

    :cvar: TAG_NAME: The name of the HTML tag ('select').
    :vartype: TAG_NAME: ClassVar[str]
    :param: name: The name attribute of the form field.
    :type: name: RequiredStr
    :param: required: Whether the field is required. Defaults to False.
    :type: required: bool
    :param: label: The label for the form field, if any. Defaults to None.
    :type: label: RequiredStr | None
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    :param: children: A tuple of child options contained within this element.
    :type: children: tuple[OptionElement, ...]
    :param: default: The default selected option value. If None (default), no option is
        selected by default, but a placeholder option may be added if there are multiple
        options.
    :type: default: str | None
    """

    TAG_NAME: ClassVar[str] = "select"
    children: tuple[OptionElement, ...] = Field(
        default_factory=tuple,
        exclude=True,
        validation_alias=AliasChoices("choices", "options"),
    )
    default: str | None = Field(None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def set_default_selection(cls, data: Any) -> Any:
        """Set the default selected option based on the `default` attribute.

        For `dict` and `__init__` input data, if `default` is None and there are
        multiple options available, this validator inserts a placeholder "Select an
        option" :class:`OptionElement` at the beginning of the options list.
        If `default` is set, it marks the corresponding option as selected.

        :return: The updated data with the default selection set.
        :rtype: Any
        """
        if isinstance(data, dict) and (
            children_key := next(
                (key for key in ["choices", "options", "children"] if key in data), None
            )
        ):
            if (default := data.get("default")) is None:
                if len(data[children_key]) > 1:
                    data[children_key] = (
                        OptionElement(value="", label="Select an option"),
                        *data[children_key],
                    )
            else:
                raw_children = list(data[children_key])
                data[children_key] = []
                for _ in range(len(raw_children)):
                    option = OptionElement.model_validate(raw_children.pop(0))
                    if option.value == default:
                        data[children_key].append(
                            option.model_copy(update={"selected": True})
                        )
                        break
                    data[children_key].append(option)
                data[children_key].extend(raw_children)
        return data

    @property
    def prepend_raw(self) -> str:
        """Return raw HTML to prepend before the select element.

        This property returns an icon indicating that the select element can be expanded.

        :return: An HTML span element with an icon for dropdown indication.
        :rtype: str
        """
        return '<span class="material-symbols-outlined">arrow_drop_down</span>'


class BaseInputElement(FormFieldMixin, VoidHTMLElement, ABC):
    """Define base class for the input HTML element.

    :cvar: TAG_NAME: The name of the HTML tag ('input').
    :vartype: TAG_NAME: ClassVar[str]
    :param: name: The name attribute of the form field.
    :type: name: RequiredStr
    :param: required: Whether the field is required. Defaults to False.
    :type: required: bool
    :param: label: The label for the form field, if any. Defaults to None.
    :type: label: RequiredStr | None
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    """

    TAG_NAME: ClassVar[str] = "input"

    @computed_field
    @property
    @abstractmethod
    def type(self) -> InputType:
        """Return the type of the input element.

        This property must be implemented by subclasses to specify the input type
        (e.g., text, number, checkbox).

        :return: The type of the input element.
        :rtype: InputType
        """


class TextInputElement(TextFieldMixin, BaseInputElement):
    """Define a text input HTML element.

    :cvar: TAG_NAME: The name of the HTML tag ('input').
    :vartype: TAG_NAME: ClassVar[str]
    :param: name: The name attribute of the form field.
    :type: name: RequiredStr
    :param: required: Whether the field is required. Defaults to False
    :type: required: bool
    :param: label: The label for the form field, if any. Defaults to None
    :type: label: RequiredStr | None
    :param: placeholder: The placeholder text for the form field, if any. Defaults to
        None.
    :type: placeholder: RequiredStr | None
    :param: maxlength: The maximum length of the text input. If None, no maximum
        length is enforced. Defaults to None.
    :type: maxlength: PositiveInt | None
    :param: minlength: The minimum length of the text input. If None, no minimum
        length is enforced. Defaults to None.
    :type: minlength: PositiveInt | None
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    :param: pattern: A regex pattern that the input value must match. If None, no
        pattern is enforced. Defaults to None.
    :type: pattern: RequiredStr | None
    """

    pattern: RequiredStr | None = None

    @computed_field
    @property
    def type(self) -> InputType:
        """Return the type of the input element.

        :return: The type of the input element (`InputType.TEXT`).
        :rtype: InputType
        """
        return InputType.TEXT


class NumberInputElement(TypeableFieldMixin, BaseInputElement):
    """Define a number input HTML element.

    :cvar: TAG_NAME: The name of the HTML tag ('input').
    :vartype: TAG_NAME: ClassVar[str]
    :param: name: The name attribute of the form field.
    :type: name: RequiredStr
    :param: required: Whether the field is required. Defaults to False
    :type: required: bool
    :param: label: The label for the form field, if any. Defaults to None
    :type: label: RequiredStr | None
    :param: placeholder: The placeholder text for the form field, if any. Defaults to
        None.
    :type: placeholder: RequiredStr | None
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    :param: max: The maximum value allowed for the number input. If None, no maximum
        is enforced. Defaults to None.
    :type: max: float | None
    :param: min: The minimum value allowed for the number input. If None, no
        minimum is enforced. Defaults to None.
    :type: min: float | None
    :param: step: The step value for the number input, defining the intervals at which
        the value can change. If None, no specific step is enforced. Defaults to None.
    """

    max: float | None = Field(None, validation_alias=AliasChoices("max", "le"))
    min: float | None = Field(None, validation_alias=AliasChoices("min", "ge"))
    step: float | None = None

    @model_validator(mode="before")
    @classmethod
    def get_max_min_from_lt_gt(cls, data: Any) -> Any:
        """Set 'le' and 'ge' from 'lt' and 'gt' if 'step' is provided.

        If the input data is a dictionary and contains a "step" key, it sets the "le"
        (less than or equal) and "ge" (greater than or equal) keys based
        on the "lt" (less than) and "gt" (greater than) keys, respectively, if they
        weren't directly provided.

        :param data: The input data, which can be a dictionary or other types.
        :type data: Any
        :return: The validated data with "le" and "ge" set if applicable.
        :rtype: Any
        """
        if isinstance(data, dict):
            step = data.get("step")
            if step is not None:
                if "le" not in data and (lt := data.get("lt")) is not None:
                    data["le"] = lt - step
                if "ge" not in data and (gt := data.get("gt")) is not None:
                    data["ge"] = gt + step
        return data

    @computed_field
    @property
    def type(self) -> InputType:
        """Return the type of the input element.

        :return: The type of the input element (`InputType.NUMBER`).
        :rtype: InputType
        """
        return InputType.NUMBER


class CheckboxInputElement(BaseInputElement):
    """Define a checkbox input HTML element.

    :cvar: TAG_NAME: The name of the HTML tag ('input').
    :vartype: TAG_NAME: ClassVar[str]
    :param: name: The name attribute of the form field.
    :type: name: RequiredStr
    :param: required: Whether the field is required. Defaults to False.
    :type: required: bool
    :param: label: The label for the form field, if any. Defaults to None.
    :type: label: RequiredStr | None
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    :param: checked: Whether the checkbox is checked by default. Defaults to False.
    :type: checked: bool
    """

    checked: bool = Field(default=False, validation_alias="default")

    @computed_field
    @property
    def type(self) -> InputType:
        """Return the type of the input element.

        :return: The type of the input element (`InputType.CHECKBOX`).
        :rtype: InputType
        """
        return InputType.CHECKBOX

    @property
    def append_raw(self) -> str:
        """Return raw HTML to append after the checkbox input element.

        This property returns HTML for a checkmark icon that visually represents the
        checkbox state.

        :return: An HTML div element with checkmark icons.
        :rtype: str
        """
        return (
            '<div class="checkmark">'
            '<span class="material-symbols-outlined unchecked">check_box_outline_blank</span>'
            '<span class="material-symbols-outlined checked">check_box</span>'
            "</div>"
        )


class SubmitButtonElement(HTMLElement):
    """Define a submit button HTML element with optional icon.

    :cvar: TAG_NAME: The name of the HTML tag ('button').
    :vartype: TAG_NAME: ClassVar[str]
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    :param: children: A tuple of child HTML entities contained within this element.
    :type: children: tuple[BaseHTMLEntity, ...]
    :param: label: The label text for the button.
    :type: label: RequiredStr
    :param: icon: The name of the icon to display on the button, if any. Defaults to
        None.
    :type: icon: RequiredStr | None
    """

    TAG_NAME: ClassVar[str] = "button"
    label: RequiredStr = Field(exclude=True, validation_alias="text")
    icon: RequiredStr | None = Field(None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def create_from_str(cls, data: Any) -> Any:
        """Create a SubmitButtonElement instance from a string.

        Converts a string into a `SubmitButtonElement` instance, allowing it to be used
        as a button with the string as its label.

        :param data: The input data.
        :type data: Any
        :return: The validated data.
        :rtype: Any
        """
        if isinstance(data, str):
            return {"label": data}
        return data

    @model_validator(mode="before")
    @classmethod
    def _set_children_by_label(cls, data: Any) -> Any:
        if isinstance(data, str):
            data = {"label": data}
        if isinstance(data, dict) and "label" in data:
            if (icon := data.get("icon")) is None:
                data["children"] = (TextContent(text=data["label"]),)
            else:
                data["children"] = (
                    SpanElement(label=icon, classes=("material-symbols-outlined",)),
                    SpanElement(label=data["label"]),
                )
        return data

    @computed_field
    @property
    def type(self) -> str:
        """Return the type of the button element ('submit').

        :return: The type of the button element ('submit').
        :rtype: str
        """
        return "submit"


class FormElement(HTMLElement):
    """Define a form HTML element with a submit button.

    :cvar: TAG_NAME: The name of the HTML tag ('form').
    :vartype: TAG_NAME: ClassVar[str]
    :param: classes: A tuple of unique CSS class names associated with the element.
    :type: classes: UniqueList[HTMLClassName]
    :param: id: The ID attribute of the element.
    :type: id: RequiredStr | None
    :param: title: The title attribute of the element, used for tooltips descriptions.
    :type: title: RequiredStr | None
    :param: children: A tuple of child HTML entities contained within this element.
    :type: children: tuple[BaseHTMLEntity, ...]
    :param: action: The URL to which the form data will be submitted. Defaults to an
        empty string, meaning the form will submit to the current page.
    :type: action: str
    :param: method: The HTTP method for the form submission. Defaults to
        :attr:`FormMethod.POST`.
    :type: FormMethod
    :param: submit_button: The submit button element to be included in the form.
    :type: submit_button: SubmitButtonElement
    """

    TAG_NAME: ClassVar[str] = "form"
    action: str = ""
    method: FormMethod = FormMethod.POST
    submit_button: SubmitButtonElement = Field(
        SubmitButtonElement(
            label="send", classes=("material-symbols-outlined", "text")
        ),
        exclude=True,
    )

    @property
    def inner_html(self) -> str:
        """Return the inner HTML content of the form.

        This property generates the HTML for all child elements contained within the
        form and appends the submit button's HTML.

        :return: The inner HTML content as a string, including the submit button.
        :rtype: str
        """
        return super().inner_html + self.submit_button.to_html()


@validate_call
@ttl_cache(ttl=_SEVEN_DAYS, maxsize=4)
def get_executor_hosts_fieldset(executor_hosts: frozenset[str]) -> FieldsetElement:
    """Create a fieldset for executor hosts with a legend and input fields.

    :param executor_hosts: A variable number of executor host strings.
    :return: A FieldsetElement containing the input fields for the executor hosts.
    :rtype: FieldsetElement
    """
    return FieldsetElement(
        legend="Executor Host",
        children=[
            SelectElement(
                children=executor_hosts,
                name="hostname",
                title="Select the hostname of the target system for snippet execution.",
                label="Select host",
                required=True,
            ),
        ],
    )


FormFieldElement = BaseInputElement | SelectElement | TextareaElement

EXTRA_ARGS_INPUT = TextInputElement(
    name="extra",
    placeholder="e.g. --verbose",
    title="Any extra args to pass to the snippet execution command",
    label="Extra Args",
)
