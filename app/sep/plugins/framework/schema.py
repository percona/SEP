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

"""Define the plugin schema DSL for schema-driven plugin form and list views."""

__all__ = [
    "AnyField",
    "BaseField",
    "BoolField",
    "Capabilities",
    "Choice",
    "ChoiceField",
    "Column",
    "ColumnFormat",
    "DateTimeField",
    "FileField",
    "FloatField",
    "FormSection",
    "HostField",
    "IntegerField",
    "ListView",
    "MultiChoiceField",
    "PluginSchema",
    "SchemaBaseModel",
    "SchemaField",
    "ServiceField",
    "StringField",
    "TableField",
    "TextAreaField",
    "YamlField",
]

from enum import auto, StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.core.utils.fields import EnumFieldMixin, NonEmptyStr
from app.inventory.models import ServiceTypeEnum

_FIELD_NAME_PATTERN = r"^[A-Za-z_](?:[\w-]*\w)?$"


class SchemaBaseModel(BaseModel):
    """Define the base model for every model in the plugin schema DSL.

    :cvar model_config: Serialises to camelCase JSON, accepts either camelCase
        or snake_case keys on input, and forbids unknown keys.
    :vartype model_config: ConfigDict
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Choice(SchemaBaseModel):
    """Represent one option in a choice or multi-choice field.

    :param label: The human-readable label displayed for the choice.
    :type label: NonEmptyStr
    :param value: The value submitted when the choice is selected.
    :type value: NonEmptyStr
    """

    label: NonEmptyStr
    value: NonEmptyStr


class ColumnFormat(EnumFieldMixin, StrEnum):
    """Enumerate the supported list-view column formatting hints.

    :cvar TEXT: Render the column value as plain text.
    :vartype TEXT: str
    :cvar CHIP: Render the column value as a Material UI chip.
    :vartype CHIP: str
    :cvar STATUS: Render the column value as a colour-coded status badge.
    :vartype STATUS: str
    :cvar DATE: Render the column value as an absolute date.
    :vartype DATE: str
    :cvar RELATIVE: Render the column value as a relative time (for example,
        "2 hours ago").
    :vartype RELATIVE: str
    :cvar CODE: Render the column value in a monospaced code font.
    :vartype CODE: str
    """

    TEXT = auto()
    CHIP = auto()
    STATUS = auto()
    DATE = auto()
    RELATIVE = auto()
    CODE = auto()


class BaseField(SchemaBaseModel):
    """Define the abstract base for every concrete field in the plugin schema DSL.

    Concrete subclasses add a ``field_type`` discriminator and any
    type-specific constraints. Cross-field validation (for example,
    ``min_length <= max_length`` or ``depends_on`` target existence) is
    deliberately not enforced here — the DSL is declarative and plugins
    validate their own schema contents at the plugin level.

    :param name: The form-state key for the field; must match Python
        identifier rules, optionally with internal hyphens.
    :type name: NonEmptyStr
    :param label: The human-readable label displayed next to the field.
    :type label: NonEmptyStr
    :param required: Whether the field must be provided when the form is
        submitted. Defaults to ``False``.
    :type required: bool
    :param description: Optional helper text rendered beneath the field.
        Defaults to ``None``.
    :type description: NonEmptyStr | None
    :param default: Optional default value pre-filled when the form is
        rendered. Typed permissively because consumer defaults may be
        scalars, lists, or dicts depending on the field type. Defaults to
        ``None``.
    :type default: Any | None
    """

    name: Annotated[NonEmptyStr, Field(pattern=_FIELD_NAME_PATTERN)]
    label: NonEmptyStr
    required: bool = False
    description: NonEmptyStr | None = None
    default: Any | None = None


class BoolField(BaseField):
    """Represent a boolean toggle field.

    :param field_type: The discriminator literal; always ``"bool"`` for this
        class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["bool"]
    """

    field_type: Literal["bool"] = Field(
        "bool", alias="type", serialization_alias="type"
    )


class ChoiceField(BaseField):
    """Represent a single-select dropdown field.

    :param field_type: The discriminator literal; always ``"choice"`` for this
        class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["choice"]
    :param choices: The non-empty list of options the user can choose from.
    :type choices: list[Choice]
    """

    field_type: Literal["choice"] = Field(
        "choice", alias="type", serialization_alias="type"
    )
    choices: list[Choice] = Field(..., min_length=1)


class FloatField(BaseField):
    """Represent a float numeric input field.

    :param field_type: The discriminator literal; always ``"float"`` for this
        class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["float"]
    :param ge: Optional lower bound (inclusive) for accepted values. Defaults
        to ``None``.
    :type ge: float | None
    :param le: Optional upper bound (inclusive) for accepted values. Defaults
        to ``None``.
    :type le: float | None
    :param step: Optional step size for the input control. Defaults to
        ``None``.
    :type step: float | None
    """

    field_type: Literal["float"] = Field(
        "float", alias="type", serialization_alias="type"
    )
    ge: float | None = None
    le: float | None = None
    step: float | None = None


class IntegerField(BaseField):
    """Represent an integer numeric input field.

    :param field_type: The discriminator literal; always ``"integer"`` for this
        class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["integer"]
    :param ge: Optional lower bound (inclusive) for accepted values. Defaults
        to ``None``.
    :type ge: int | None
    :param le: Optional upper bound (inclusive) for accepted values. Defaults
        to ``None``.
    :type le: int | None
    :param step: Optional step size for the input control. Defaults to
        ``None``.
    :type step: int | None
    """

    field_type: Literal["integer"] = Field(
        "integer", alias="type", serialization_alias="type"
    )
    ge: int | None = None
    le: int | None = None
    step: int | None = None


class MultiChoiceField(BaseField):
    """Represent a multi-select dropdown field.

    :param field_type: The discriminator literal; always ``"multi_choice"``
        for this class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["multi_choice"]
    :param choices: The non-empty list of options the user can choose from.
    :type choices: list[Choice]
    """

    field_type: Literal["multi_choice"] = Field(
        "multi_choice", alias="type", serialization_alias="type"
    )
    choices: list[Choice] = Field(..., min_length=1)


class StringField(BaseField):
    """Represent a single-line string input field.

    :param field_type: The discriminator literal; always ``"string"`` for this
        class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["string"]
    :param min_length: Optional minimum character length. Defaults to
        ``None``.
    :type min_length: int | None
    :param max_length: Optional maximum character length. Defaults to
        ``None``.
    :type max_length: int | None
    :param pattern: Optional regular expression the value must match.
        Defaults to ``None``.
    :type pattern: NonEmptyStr | None
    :param placeholder: Optional placeholder text displayed when the field is
        empty. Defaults to ``None``.
    :type placeholder: NonEmptyStr | None
    """

    field_type: Literal["string"] = Field(
        "string", alias="type", serialization_alias="type"
    )
    min_length: int | None = Field(default=None, ge=1)
    max_length: int | None = Field(default=None, ge=1)
    pattern: NonEmptyStr | None = None
    placeholder: NonEmptyStr | None = None


class TextAreaField(BaseField):
    """Represent a multi-line string input field.

    :param field_type: The discriminator literal; always ``"textarea"`` for
        this class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["textarea"]
    :param rows: Optional number of visible text rows. Defaults to ``None``.
    :type rows: int | None
    :param placeholder: Optional placeholder text displayed when the field is
        empty. Defaults to ``None``.
    :type placeholder: NonEmptyStr | None
    """

    field_type: Literal["textarea"] = Field(
        "textarea", alias="type", serialization_alias="type"
    )
    rows: int | None = Field(default=None, ge=1)
    placeholder: NonEmptyStr | None = None


class DateTimeField(BaseField):
    """Represent a datetime picker field.

    :param field_type: The discriminator literal; always ``"datetime"`` for
        this class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["datetime"]
    """

    field_type: Literal["datetime"] = Field(
        "datetime", alias="type", serialization_alias="type"
    )


class FileField(BaseField):
    """Represent a file upload field.

    :param field_type: The discriminator literal; always ``"file"`` for this
        class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["file"]
    :param accept: Optional list of accepted file types, using the same
        syntax as the HTML ``accept`` attribute (for example, ``[".sql",
        ".csv"]`` or ``["image/png"]``). Defaults to ``None``.
    :type accept: list[str] | None
    """

    field_type: Literal["file"] = Field(
        "file", alias="type", serialization_alias="type"
    )
    accept: list[str] | None = None


class YamlField(BaseField):
    """Represent a YAML-syntax multi-line text input field.

    :param field_type: The discriminator literal; always ``"yaml"`` for this
        class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["yaml"]
    :param rows: Optional number of visible text rows. Defaults to ``None``.
    :type rows: int | None
    :param placeholder: Optional placeholder text displayed when the field is
        empty. Defaults to ``None``.
    :type placeholder: NonEmptyStr | None
    """

    field_type: Literal["yaml"] = Field(
        "yaml", alias="type", serialization_alias="type"
    )
    rows: int | None = Field(default=None, ge=1)
    placeholder: NonEmptyStr | None = None


class HostField(BaseField):
    """Represent an executor-target (Nomad / Celery) selector field.

    The React renderer loads options from ``GET /api/sep/hosts/`` (an SEP
    proxy endpoint that internally calls Tasks ``/hosts/`` and merges
    Inventory display names server-side). Host selection is not cascaded
    from another field — every dispatch form lists every available executor
    target.

    :param field_type: The discriminator literal; always ``"host"`` for this
        class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["host"]
    :param depends_on: **Deprecated.** Ignored by the renderer; will be
        removed in a future release after consumers have migrated.
    :type depends_on: NonEmptyStr | None
    """

    field_type: Literal["host"] = Field(
        "host", alias="type", serialization_alias="type"
    )
    depends_on: NonEmptyStr | None = None


class SchemaField(BaseField):
    """Represent an inventory database-schema selector field.

    ``depends_on`` is a forward reference to another field's ``name`` in the
    same plugin schema (typically a ``ServiceField``); the React renderer
    cascades schema options from the selected service. The referenced field
    is not validated at the schema level.

    :param field_type: The discriminator literal; always ``"schema"`` for
        this class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["schema"]
    :param depends_on: The name of the field whose value drives the list of
        available schemas.
    :type depends_on: NonEmptyStr
    """

    field_type: Literal["schema"] = Field(
        "schema", alias="type", serialization_alias="type"
    )
    depends_on: NonEmptyStr


class ServiceField(BaseField):
    """Represent an inventory service selector field.

    :param field_type: The discriminator literal; always ``"service"`` for
        this class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["service"]
    :param service_types: The list of service types the selector should offer
        (for example, ``[ServiceTypeEnum.MYSQL]``).
    :type service_types: list[ServiceTypeEnum]
    """

    field_type: Literal["service"] = Field(
        "service", alias="type", serialization_alias="type"
    )
    service_types: list[ServiceTypeEnum]


class TableField(BaseField):
    """Represent an inventory table selector field.

    ``depends_on`` is a forward reference to another field's ``name`` in the
    same plugin schema (typically a ``SchemaField``); the React renderer
    cascades table options from the selected schema. The referenced field
    is not validated at the schema level.

    :param field_type: The discriminator literal; always ``"table"`` for this
        class. Serialised as the JSON key ``"type"``.
    :type field_type: Literal["table"]
    :param depends_on: The name of the field whose value drives the list of
        available tables.
    :type depends_on: NonEmptyStr
    """

    field_type: Literal["table"] = Field(
        "table", alias="type", serialization_alias="type"
    )
    depends_on: NonEmptyStr


AnyField = Annotated[
    BoolField
    | ChoiceField
    | DateTimeField
    | FileField
    | FloatField
    | HostField
    | IntegerField
    | MultiChoiceField
    | SchemaField
    | ServiceField
    | StringField
    | TableField
    | TextAreaField
    | YamlField,
    Field(discriminator="field_type"),
]
"""Discriminated union of every concrete field class in the plugin schema DSL."""


class FormSection(SchemaBaseModel):
    """Represent a labelled group of related fields rendered as one fieldset.

    :param title: The section heading displayed above the grouped fields.
    :type title: NonEmptyStr
    :param description: Optional helper text rendered beneath the section
        heading. Defaults to ``None``.
    :type description: NonEmptyStr | None
    :param fields: The list of fields belonging to this section.
    :type fields: list[AnyField]
    """

    title: NonEmptyStr
    description: NonEmptyStr | None = None
    fields: list[AnyField]


class Column(SchemaBaseModel):
    """Represent one column in a plugin list view.

    :param key: The task attribute path this column displays (for example,
        ``"status"`` or ``"target.service"``).
    :type key: NonEmptyStr
    :param label: The human-readable column header.
    :type label: NonEmptyStr
    :param sortable: Whether the column can be used to sort the list.
        Defaults to ``False``.
    :type sortable: bool
    :param format: Optional formatting hint applied when rendering the
        column values. Defaults to ``None``.
    :type format: ColumnFormat | None
    """

    key: NonEmptyStr
    label: NonEmptyStr
    sortable: bool = False
    format: ColumnFormat | None = None


class ListView(SchemaBaseModel):
    """Represent the list-view configuration for a plugin.

    :param columns: The ordered list of columns displayed in the list view.
    :type columns: list[Column]
    :param default_sort: Optional key of the column to sort by on first
        render. Prefix with ``-`` for descending order (for example,
        ``"-lastRun"``). The unprefixed key must match one of the declared
        column keys. Defaults to ``None``.
    :type default_sort: NonEmptyStr | None
    """

    columns: list[Column]
    default_sort: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_default_sort_references_column(self) -> Self:
        """Ensure ``default_sort`` (stripped of one leading ``-``) matches a column.

        Exactly one leading ``-`` is stripped to mirror the React consumer,
        which strips a single leading ``-`` via ``replace(/^-/, '')`` when
        deriving the initial sort column; a schema with multiple leading
        dashes (for example, ``"--lastRun"``) would silently fail to match
        a column at render time.

        :return: The validated list view instance.
        :rtype: ListView
        :raises ValueError: If ``default_sort`` does not reference a declared
            column key.
        """
        if self.default_sort is None:
            return self
        target = self.default_sort.removeprefix("-")
        valid_keys = {column.key for column in self.columns}
        if target not in valid_keys:
            raise ValueError(
                f"default_sort {self.default_sort!r} references unknown column key; "
                f"valid keys: {sorted(valid_keys)}"
            )
        return self


class Capabilities(SchemaBaseModel):
    """Represent plugin-level feature flags.

    :param chaining: Whether the plugin supports chaining tasks together.
        Defaults to ``False``.
    :type chaining: bool
    :param alert_on_fail: Whether the plugin supports configuring a PMM
        alert when a task fails. Defaults to ``False``.
    :type alert_on_fail: bool
    :param scheduling: Whether the plugin supports scheduling tasks on a
        periodic interval. Defaults to ``False``.
    :type scheduling: bool
    """

    chaining: bool = False
    alert_on_fail: bool = False
    scheduling: bool = False


class PluginSchema(SchemaBaseModel):
    """Represent a plugin's complete schema: form sections, list view, capabilities.

    :param name: The plugin identifier; must match Python identifier rules,
        optionally with internal hyphens.
    :type name: NonEmptyStr
    :param display_name: The human-readable plugin title displayed in the UI.
    :type display_name: NonEmptyStr
    :param description: Optional helper text describing the plugin's
        purpose. Defaults to ``None``.
    :type description: NonEmptyStr | None
    :param task_type: Optional task-type identifier used when creating tasks
        via the shared task API. Defaults to ``None``.
    :type task_type: NonEmptyStr | None
    :param forms: The ordered list of form sections the plugin renders when
        creating a task.
    :type forms: list[FormSection]
    :param capabilities: Optional plugin-level feature flags. Defaults to
        ``None``.
    :type capabilities: Capabilities | None
    :param list_view: The list-view configuration for the plugin.
    :type list_view: ListView
    """

    name: Annotated[NonEmptyStr, Field(pattern=_FIELD_NAME_PATTERN)]
    display_name: NonEmptyStr
    description: NonEmptyStr | None = None
    task_type: NonEmptyStr | None = None
    forms: list[FormSection]
    capabilities: Capabilities | None = None
    list_view: ListView

    @model_validator(mode="after")
    def _validate_unique_field_names(self) -> Self:
        """Ensure every field across every section has a unique ``name``.

        :return: The validated plugin schema instance.
        :rtype: PluginSchema
        :raises ValueError: If any field ``name`` is reused across form
            sections.
        """
        seen = set()
        duplicates = []
        for section in self.forms:
            for field in section.fields:
                if field.name in seen:
                    duplicates.append(field.name)
                else:
                    seen.add(field.name)
        if duplicates:
            raise ValueError(
                f"duplicate field name(s) across form sections: "
                f"{sorted(set(duplicates))}"
            )
        return self
