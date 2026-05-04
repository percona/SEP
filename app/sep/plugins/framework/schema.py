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
    "ScriptPreviewField",
    "ServiceField",
    "StringField",
    "TableField",
    "TextAreaField",
    "YamlField",
]

from enum import auto, StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.utils.fields import EnumFieldMixin, NonEmptyStr
from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework.rules import (
    CardinalityRule,
    FailRule,
    FieldGate,
)

_FIELD_NAME_PATTERN = r"^[A-Za-z_](?:[\w-]*\w)?$"


class SchemaBaseModel(BaseModel):
    """Define the base model for every model in the plugin schema DSL.

    :cvar model_config: Serialises to snake_case JSON (no alias translation),
        forbids unknown keys, and accepts arbitrary types so rule envelopes
        carrying :class:`Predicate` instances validate.
    :vartype model_config: ConfigDict
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        arbitrary_types_allowed=True,
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
    :param requires: Optional list of binary self-cardinality gates: when
        any gate's ``when`` predicate matches, the field must be present.
        Defaults to ``None``.
    :type requires: list[FieldGate] | None
    :param forbidden: Optional list of binary self-cardinality gates: when
        any gate's ``when`` predicate matches, the field must be absent.
        Defaults to ``None``.
    :type forbidden: list[FieldGate] | None
    """

    name: Annotated[NonEmptyStr, Field(pattern=_FIELD_NAME_PATTERN)]
    label: NonEmptyStr
    required: bool = False
    description: NonEmptyStr | None = None
    default: Any | None = None
    requires: list[FieldGate] | None = None
    forbidden: list[FieldGate] | None = None


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
    """

    field_type: Literal["host"] = Field(
        "host", alias="type", serialization_alias="type"
    )


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


class ScriptPreviewField(BaseField):
    """Represent a read-only field that renders a backend-fetched script preview.

    The renderer fetches ``endpoint_url`` on mount, and re-fetches whenever
    any sibling field listed in ``depends_on`` changes value (debounced and
    cancellation-safe). The response shape is
    ``{content: str, language: str, is_truncated: bool}``.

    :param field_type: The discriminator literal; always
        ``"script_preview"`` for this class. Serialised as the JSON key
        ``"type"``.
    :type field_type: Literal["script_preview"]
    :param endpoint_url: The fully-resolved URL the renderer fetches preview
        content from, relative to the FE ``apiClient`` base (``/api``). Schema
        synthesisers should bake any plugin-specific path segments (for
        example, ``/plugins/snippets/{filename}/script-preview``) here at
        schema build time rather than templating client-side.
    :type endpoint_url: NonEmptyStr
    :param depends_on: Names of sibling fields whose values trigger a
        re-fetch when changed. Empty (the default) means fetch once on
        mount.
    :type depends_on: list[NonEmptyStr]
    :param language: Optional default highlighter language hint used when
        the backend response omits ``language``. Defaults to ``None``.
    :type language: NonEmptyStr | None
    """

    field_type: Literal["script_preview"] = Field(
        "script_preview", alias="type", serialization_alias="type"
    )
    endpoint_url: NonEmptyStr
    depends_on: list[NonEmptyStr] = Field(default_factory=list)
    language: NonEmptyStr | None = None


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
    | ScriptPreviewField
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
    :param cardinality_rules: Optional cross-field cardinality constraints
        scoped to the fields in this section. Defaults to ``None``.
    :type cardinality_rules: list[CardinalityRule] | None
    :param fail_when: Optional predicate-only invariants scoped to this
        section. Defaults to ``None``.
    :type fail_when: list[FailRule] | None
    """

    title: NonEmptyStr
    description: NonEmptyStr | None = None
    fields: list[AnyField]
    cardinality_rules: list[CardinalityRule] | None = None
    fail_when: list[FailRule] | None = None


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


def _collect_reference_errors(
    scope_path: str,
    names: set[str],
    declared_field_names: set[str],
    errors: list[str],
    *,
    allow_implicit_self: bool = False,
) -> None:
    """Append messages to ``errors`` for any unknown or hyphenated rule names.

    :param scope_path: A human-readable path to the rule emitting the names,
        used in failure messages.
    :type scope_path: str
    :param names: The set of field names referenced by the rule.
    :type names: set[str]
    :param declared_field_names: The set of names declared anywhere in the
        plugin schema's form tree.
    :type declared_field_names: set[str]
    :param errors: A mutable list to which failure messages are appended.
    :type errors: list[str]
    :param allow_implicit_self: When ``True``, suppress the descriptive
        suffix on unknown-field errors (used for ``BaseField`` gates whose
        implicit-self target is the field carrying the rule).
    :type allow_implicit_self: bool
    """
    for name in names:
        if "-" in name:
            errors.append(
                f"{scope_path} references field {name!r}, but field names that "
                "participate in conditional rules must be valid Python "
                "identifiers (no hyphens)."
            )
            continue
        if name not in declared_field_names:
            suffix = (
                ""
                if allow_implicit_self
                else " (the rule names a field that does not exist in any form section)"
            )
            errors.append(f"{scope_path} references unknown field {name!r}{suffix}.")


def _collect_basefield_gate_errors(
    field: "AnyField",
    declared_field_names: set[str],
    errors: list[str],
) -> None:
    """Walk a BaseField's ``requires`` / ``forbidden`` gates."""
    for primitive in ("requires", "forbidden"):
        for rule_index, gate in enumerate(getattr(field, primitive) or []):
            references = gate.when.referenced_fields() | {field.name}
            _collect_reference_errors(
                f"BaseField {field.name!r} {primitive}[{rule_index}]",
                references,
                declared_field_names,
                errors,
                allow_implicit_self=True,
            )


def _collect_cardinality_rule_errors(
    rules: list[CardinalityRule] | None,
    scope_label: str,
    declared_field_names: set[str],
    errors: list[str],
) -> None:
    """Walk a list of :class:`CardinalityRule` instances."""
    for rule_index, rule in enumerate(rules or []):
        references = set(rule.fields)
        if rule.when is not None:
            references |= rule.when.referenced_fields()
        _collect_reference_errors(
            f"{scope_label} cardinality_rules[{rule_index}]",
            references,
            declared_field_names,
            errors,
        )


def _collect_fail_rule_errors(
    rules: list[FailRule] | None,
    scope_label: str,
    declared_field_names: set[str],
    errors: list[str],
) -> None:
    """Walk a list of :class:`FailRule` instances."""
    for rule_index, rule in enumerate(rules or []):
        references = rule.fail_when.referenced_fields() | set(rule.error_fields)
        _collect_reference_errors(
            f"{scope_label} fail_when[{rule_index}]",
            references,
            declared_field_names,
            errors,
        )


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
    :param cardinality_rules: Optional schema-wide cross-field cardinality
        constraints. Defaults to ``None``.
    :type cardinality_rules: list[CardinalityRule] | None
    :param fail_when: Optional schema-wide predicate-only invariants.
        Defaults to ``None``.
    :type fail_when: list[FailRule] | None
    """

    name: Annotated[NonEmptyStr, Field(pattern=_FIELD_NAME_PATTERN)]
    display_name: NonEmptyStr
    description: NonEmptyStr | None = None
    task_type: NonEmptyStr | None = None
    forms: list[FormSection]
    capabilities: Capabilities | None = None
    list_view: ListView
    cardinality_rules: list[CardinalityRule] | None = None
    fail_when: list[FailRule] | None = None

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

    @model_validator(mode="after")
    def _validate_rule_field_references(self) -> Self:
        """Resolve every conditional-rule field reference against the schema tree.

        Performs Tier-2 validation: walks every BaseField ``requires`` /
        ``forbidden`` rule, every FormSection ``cardinality_rules`` /
        ``fail_when`` rule, and every PluginSchema-scope rule. For each, it
        collects the predicate's referenced fields plus the rule's target
        ``fields`` / ``error_fields`` / implicit-self target (for BaseField
        gates) and verifies each name resolves to a known field declared in
        the schema. Hyphenated field names are also rejected here since they
        cannot resolve to Python attributes via ``getattr`` at runtime.

        :return: The validated plugin schema instance.
        :rtype: PluginSchema
        :raises ValueError: If any rule references a field that does not
            exist in the schema, or whose name contains a hyphen.
        """
        declared_field_names = {
            field.name for section in self.forms for field in section.fields
        }
        errors = []
        for section_index, section in enumerate(self.forms):
            section_label = f"FormSection[{section_index}] {section.title!r}"
            for field in section.fields:
                _collect_basefield_gate_errors(field, declared_field_names, errors)
            _collect_cardinality_rule_errors(
                section.cardinality_rules, section_label, declared_field_names, errors
            )
            _collect_fail_rule_errors(
                section.fail_when, section_label, declared_field_names, errors
            )
        schema_label = f"PluginSchema {self.name!r}"
        _collect_cardinality_rule_errors(
            self.cardinality_rules, schema_label, declared_field_names, errors
        )
        _collect_fail_rule_errors(
            self.fail_when, schema_label, declared_field_names, errors
        )
        if errors:
            raise ValueError("; ".join(errors))
        return self
