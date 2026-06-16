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

"""Derive ``PluginSchema`` form objects from a create model's fields and markers.

The functions here read each field's :class:`~pydantic.fields.FieldInfo`
(annotation, default, ``metadata``) and emit the existing
:class:`~app.sep.plugins.framework.schema.BaseField` /
:class:`~app.sep.plugins.framework.schema.FormSection` /
:class:`~app.sep.plugins.framework.schema.PluginSchema` objects, so the wire
format is byte-identical to a hand-written schema.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import UnionType
from typing import Any, get_args, get_origin, Literal, TYPE_CHECKING, Union

import annotated_types
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from app.sep.plugins.framework.form_dsl.markers import (
    Choices,
    FieldWidget,
    Forbidden,
    FormLayout,
    FormRules,
    HostRef,
    Requires,
    SchemaRef,
    SectionRules,
    ServiceRef,
    TableRef,
    Ui,
)
from app.sep.plugins.framework.rules import FieldGate
from app.sep.plugins.framework.schema import (
    BaseField,
    BoolField,
    Choice,
    ChoiceField,
    Column,
    DateTimeField,
    FloatField,
    FormSection,
    HostField,
    IntegerField,
    ListView,
    MultiChoiceField,
    PluginSchema,
    SchemaField,
    ServiceField,
    StringField,
    TableField,
    TextAreaField,
    YamlField,
)

if TYPE_CHECKING:
    from app.sep.plugins.framework.form_dsl.model import AppFormModel

__all__ = [
    "build_runtime_schema",
    "derive_form_sections",
    "derive_plugin_schema",
    "find_ref_marker",
    "resolve_base",
]

_REF_TYPES = (ServiceRef, SchemaRef, TableRef, HostRef)
_NONE_TYPE = type(None)
_SIMPLE_SCALAR_FIELDS: dict[type, type[BaseField]] = {
    bool: BoolField,
    datetime: DateTimeField,
}


@dataclass(frozen=True, slots=True)
class _FieldSpec:
    """Pair a derived field with its section placement and declaration order.

    :param base_field: The derived schema field.
    :param section: The layout-section key from :attr:`Ui.section`.
    :param order: The within-section sort key from :attr:`Ui.order`.
    :param index: The declaration index, used as a stable tiebreaker.
    """

    base_field: BaseField
    section: str
    order: int
    index: int


def resolve_base(annotation: Any) -> tuple[Any, bool]:
    """Return ``(base, is_list)`` after stripping ``Annotated`` / ``| None`` / list.

    ``Annotated`` wrappers, ``None``/``EmptyStrToNone`` union members, and a
    ``list[...]`` container are peeled away so the inference sees the underlying
    scalar (and learns whether the field is a list).

    :param annotation: The field's resolved annotation.
    :return: The base type (or ``Literal[...]`` / enum class) and whether the
        field is a list.
    """
    current = _strip_annotated(annotation)
    if get_origin(current) in (Union, UnionType):
        members = [
            stripped
            for arg in get_args(current)
            if (stripped := _strip_annotated(arg)) is not _NONE_TYPE
        ]
        current = members[0] if members else _NONE_TYPE
    if get_origin(current) is list:
        return _strip_annotated(get_args(current)[0]), True
    return current, False


def _annotation_accepts_str(annotation: Any) -> bool:
    """Return whether ``annotation`` admits ``str`` (directly or in a union)."""
    current = _strip_annotated(annotation)
    if get_origin(current) in (Union, UnionType):
        return any(_strip_annotated(arg) is str for arg in get_args(current))
    return current is str


def _strip_annotated(annotation: Any) -> Any:
    """Return the underlying type of an ``Annotated[...]``, or ``annotation`` itself."""
    metadata = getattr(annotation, "__metadata__", None)
    return annotation.__args__[0] if metadata is not None else annotation


def _is_enum(annotation: Any) -> bool:
    """Return whether ``annotation`` is an :class:`enum.Enum` subclass."""
    return isinstance(annotation, type) and issubclass(annotation, Enum)


def _is_literal(annotation: Any) -> bool:
    """Return whether ``annotation`` is a ``typing.Literal[...]``."""
    return get_origin(annotation) is Literal


def _field_default(field_info: FieldInfo) -> Any:
    """Return the field's default value, or ``None`` when it has none."""
    default = field_info.get_default(call_default_factory=False)
    return None if default is PydanticUndefined else default


def find_ref_marker(
    metadata: list[Any],
) -> ServiceRef | SchemaRef | TableRef | HostRef | None:
    """Return the single reference marker in ``metadata``, or ``None``.

    Shared with the task-payload resolver so it consumes the same marker
    introspection (``_REF_TYPES`` / :func:`_find_marker`) the schema derivation
    uses, rather than re-scanning ``FieldInfo.metadata`` independently.

    :param metadata: A field's ``FieldInfo.metadata`` list.
    :return: The field's reference marker, or ``None`` when it declares none.
    :raises ValueError: When the field declares more than one reference marker.
    """
    return _find_marker(metadata, _REF_TYPES)


def _find_marker(metadata: list[Any], marker_types: tuple[type, ...]) -> Any:
    """Return the single marker of ``marker_types`` in ``metadata``, or ``None``.

    :param metadata: A field's ``FieldInfo.metadata`` list.
    :param marker_types: The marker classes to match.
    :return: The matching marker instance, or ``None`` when absent.
    :raises ValueError: When more than one matching marker is present.
    """
    found = [item for item in metadata if isinstance(item, marker_types)]
    if len(found) > 1:
        raise ValueError(
            f"at most one {marker_types[0].__name__}-family marker is allowed per "
            f"field, found {len(found)}"
        )
    return found[0] if found else None


def _field_ui(name: str, metadata: list[Any]) -> Ui:
    """Return the field's :class:`Ui` marker.

    :param name: The field name, used in the error message.
    :param metadata: The field's ``FieldInfo.metadata`` list.
    :return: The field's ``Ui`` marker.
    :raises ValueError: When the field declares no ``Ui`` marker.
    """
    ui = _find_marker(metadata, (Ui,))
    if ui is None:
        raise ValueError(
            f"field {name!r} is missing a Ui(...) marker; every AppFormModel field "
            "must declare Ui(label=..., section=...)"
        )
    return ui


def _gates(metadata: list[Any], marker_type: type) -> list[FieldGate]:
    """Return the field gates derived from every ``marker_type`` marker."""
    return [
        FieldGate(when=marker.when, message=marker.message)
        for marker in metadata
        if isinstance(marker, marker_type)
    ]


def _derive_choices(name: str, base: Any, choices: Choices | None) -> list[Choice]:
    """Return the choice options for a choice field.

    :param name: The field name, used in the error message.
    :param base: The field's base type (scalar, enum class, or ``Literal[...]``).
    :param choices: The explicit :class:`Choices` marker, if any.
    :return: The ordered choice options.
    :raises ValueError: When no options can be derived and none were supplied.
    """
    if choices is not None:
        return [
            Choice(value=str(value), label=label) for value, label in choices.options
        ]
    if _is_enum(base):
        return [
            Choice(value=str(member.value), label=str(member.value)) for member in base
        ]
    if _is_literal(base):
        return [Choice(value=str(arg), label=str(arg)) for arg in get_args(base)]
    raise ValueError(
        f"field {name!r} is a choice field but no options could be derived; "
        "annotate it with Choices([...]) (or an Enum / Literal base type)"
    )


def _numeric_bounds(metadata: list[Any]) -> dict[str, Any]:
    """Return ``ge`` / ``le`` bounds extracted from ``annotated_types`` metadata."""
    ge = next(
        (item.ge for item in metadata if isinstance(item, annotated_types.Ge)), None
    )
    le = next(
        (item.le for item in metadata if isinstance(item, annotated_types.Le)), None
    )
    return {"ge": ge, "le": le}


def _string_constraints(metadata: list[Any]) -> dict[str, Any]:
    """Return ``min_length`` / ``max_length`` / ``pattern`` from string metadata."""
    min_length = next(
        (
            item.min_length
            for item in metadata
            if isinstance(item, annotated_types.MinLen)
        ),
        None,
    )
    max_length = next(
        (
            item.max_length
            for item in metadata
            if isinstance(item, annotated_types.MaxLen)
        ),
        None,
    )
    pattern = next(
        (
            item.pattern
            for item in metadata
            if getattr(item, "pattern", None) is not None
        ),
        None,
    )
    return {"min_length": min_length, "max_length": max_length, "pattern": pattern}


def _build_ref_field(ref: Any, ui: Ui, common: dict[str, Any]) -> BaseField:
    """Return the reference field selected by ``ref`` with its extras applied.

    :param ref: The reference marker driving the field class.
    :param ui: The field's ``Ui`` marker, source of a cascade ``depends_on``.
    :param common: The shared ``BaseField`` keyword arguments.
    :return: The derived reference field.
    :raises ValueError: When a cascade reference omits ``Ui(depends_on=...)``.
    """
    allow_custom = ref.allow_custom or None
    if isinstance(ref, ServiceRef):
        return ServiceField(
            **common, service_types=list(ref.service_types), allow_custom=allow_custom
        )
    if isinstance(ref, SchemaRef | TableRef):
        if ui.depends_on is None:
            raise ValueError(
                f"field {common['name']!r} uses a cascade reference but omits "
                "Ui(depends_on=...); a SchemaRef / TableRef must name the field "
                "whose value drives its options"
            )
        field_class = SchemaField if isinstance(ref, SchemaRef) else TableField
        return field_class(
            **common, depends_on=ui.depends_on, allow_custom=allow_custom
        )
    return HostField(**common, allow_custom=allow_custom)


def _build_base_field(
    name: str, field_info: FieldInfo, ui: Ui, metadata: list[Any]
) -> BaseField:
    """Return the schema field derived from one model field.

    :param name: The field name (the wire ``name``).
    :param field_info: The field's Pydantic ``FieldInfo``.
    :param ui: The field's ``Ui`` marker.
    :param metadata: The field's ``FieldInfo.metadata`` list.
    :return: The derived field.
    :raises ValueError: When the base type maps to no known field kind, or a
        choice field supplies no derivable options.
    """
    common = {
        "name": name,
        "label": ui.label,
        "required": ui.required
        if ui.required is not None
        else field_info.is_required(),
        "description": ui.description,
        "default": _field_default(field_info),
        "requires": _gates(metadata, Requires) or None,
        "forbidden": _gates(metadata, Forbidden) or None,
    }

    ref_markers = [item for item in metadata if isinstance(item, _REF_TYPES)]
    if len(ref_markers) > 1:
        raise ValueError(
            f"field {name!r} declares {len(ref_markers)} reference markers; "
            "discriminated-union (one-of) reference groups are deferred to FE-4 "
            "and are not derived here — declare a single reference per field"
        )
    if ref_markers:
        ref = ref_markers[0]
        if ref.allow_custom and not _annotation_accepts_str(field_info.annotation):
            raise ValueError(
                f"field {name!r} sets allow_custom=True but its annotation does not "
                "accept str; widen it to include str (e.g. int | str) so the model "
                "accepts the free-typed value the schema advertises"
            )
        return _build_ref_field(ref, ui, common)

    base, is_list = resolve_base(field_info.annotation)
    choices = _find_marker(metadata, (Choices,))
    if ui.widget is FieldWidget.MULTI_CHOICE and not is_list:
        raise ValueError(
            f"field {name!r} uses widget=MULTI_CHOICE but its annotation is not a "
            "list; a multi-choice field must back a list type so the model accepts "
            "the submitted list of values"
        )
    if _wants_choice(choices, ui.widget, base):
        options = _derive_choices(name, base, choices)
        multi = is_list or ui.widget is FieldWidget.MULTI_CHOICE
        field_class = MultiChoiceField if multi else ChoiceField
        return field_class(**common, choices=options)

    if is_list:
        raise ValueError(
            f"field {name!r} is a list field but no multi-choice options could be "
            "derived; annotate it with Choices([...]) or use an Enum / Literal "
            "element type"
        )
    return _build_scalar_field(name, base, ui.widget, common, metadata)


def _wants_choice(
    choices: Choices | None, widget: FieldWidget | None, base: Any
) -> bool:
    """Return whether a field should derive a (multi-)choice from its base/markers."""
    return (
        choices is not None
        or widget in (FieldWidget.CHOICE, FieldWidget.MULTI_CHOICE)
        or _is_enum(base)
        or _is_literal(base)
    )


def _build_scalar_field(
    name: str,
    base: Any,
    widget: FieldWidget | None,
    common: dict[str, Any],
    metadata: list[Any],
) -> BaseField:
    """Return the non-reference, non-choice field for ``base`` / ``widget``.

    :param name: The field name, used in the error message.
    :param base: The unwrapped base type.
    :param widget: The optional widget override.
    :param common: The shared ``BaseField`` keyword arguments.
    :param metadata: The field's ``FieldInfo.metadata`` list (for numeric bounds
        and string constraints).
    :return: The derived scalar field.
    :raises ValueError: When ``base`` maps to no known field kind.
    """
    if widget is FieldWidget.TEXTAREA:
        return TextAreaField(**common)
    if widget is FieldWidget.YAML:
        return YamlField(**common)
    if base is int:
        return IntegerField(**common, **_numeric_bounds(metadata))
    if base is float:
        return FloatField(**common, **_numeric_bounds(metadata))
    if base is str:
        return StringField(**common, **_string_constraints(metadata))
    field_class = _SIMPLE_SCALAR_FIELDS.get(base)
    if field_class is None:
        raise ValueError(
            f"field {name!r}: cannot infer a form field kind from base type "
            f"{base!r}; use a Ref marker, an Enum / Literal, Choices([...]), or a "
            "Ui(widget=...) override"
        )
    return field_class(**common)


def _derive_field_specs(model: type["AppFormModel"]) -> list[_FieldSpec]:
    """Return one :class:`_FieldSpec` per model field, in declaration order."""
    specs = []
    for index, (name, field_info) in enumerate(model.model_fields.items()):
        metadata = list(field_info.metadata)
        ui = _field_ui(name, metadata)
        specs.append(
            _FieldSpec(
                base_field=_build_base_field(name, field_info, ui, metadata),
                section=ui.section,
                order=ui.order,
                index=index,
            )
        )
    return specs


def _gate_only_fields(model: type["AppFormModel"]) -> list[BaseField]:
    """Return one minimal field per model field, carrying only name and gates.

    The runtime rule plan needs only field names and their ``requires`` /
    ``forbidden`` gates, not full type inference. Building gate-only fields keeps
    rule-plan extraction at class definition cheap and independent of field-kind
    inference, so a field-kind error (an unresolvable choice, a duplicate
    reference marker) surfaces at :func:`derive_form_sections` time rather than
    on class definition.

    :param model: The create model whose fields to project.
    :return: One :class:`~app.sep.plugins.framework.schema.StringField` per model
        field, carrying its name and any field gates.
    """
    fields = []
    for name, field_info in model.model_fields.items():
        metadata = list(field_info.metadata)
        fields.append(
            StringField(
                name=name,
                label=name,
                requires=_gates(metadata, Requires) or None,
                forbidden=_gates(metadata, Forbidden) or None,
            )
        )
    return fields


def derive_form_sections(
    model: type["AppFormModel"], layout: FormLayout
) -> list[FormSection]:
    """Return the form sections derived from ``model`` grouped by ``layout``.

    Fields are grouped by :attr:`Ui.section`, ordered within a section by
    :attr:`Ui.order` then declaration order, and the sections are ordered by
    ``layout``. Section-scoped rules from the model's ``__form_rules__`` attach
    to the matching section; a layout section's ``forbidden`` gates copy onto
    :attr:`~app.sep.plugins.framework.schema.FormSection.forbidden`.

    :param model: The create model carrying the field markers.
    :param layout: The section layout naming and ordering the sections.
    :return: The derived form sections in layout order.
    :raises ValueError: When a field names a section absent from ``layout``, or a
        layout section has no fields.
    """
    specs = _derive_field_specs(model)
    layout_keys = {section.key for section in layout.sections}
    for spec in specs:
        if spec.section not in layout_keys:
            raise ValueError(
                f"field {spec.base_field.name!r} names section {spec.section!r}, "
                f"which is absent from the form layout (known: {sorted(layout_keys)})"
            )

    rules = getattr(model, "__form_rules__", FormRules())
    sections = []
    for section_layout in layout.sections:
        members = sorted(
            (spec for spec in specs if spec.section == section_layout.key),
            key=lambda spec: (spec.order, spec.index),
        )
        if not members:
            raise ValueError(
                f"layout section {section_layout.key!r} has no fields; remove it or "
                "assign a field to it"
            )
        section_rules = rules.sections.get(section_layout.key, SectionRules())
        sections.append(
            FormSection(
                title=section_layout.title,
                description=section_layout.description,
                fields=[spec.base_field for spec in members],
                collapsible=section_layout.collapsible,
                collapsed_by_default=section_layout.collapsed_by_default,
                render_after_submit=section_layout.render_after_submit,
                forbidden=list(section_layout.forbidden)
                if section_layout.forbidden
                else None,
                fail_when=list(section_rules.fail_when) or None,
                cardinality_rules=list(section_rules.cardinality_rules) or None,
            )
        )
    return sections


def derive_plugin_schema(
    model: type["AppFormModel"],
    layout: FormLayout,
    *,
    name: str,
    display_name: str,
    description: str | None = None,
    task_type: str | None = None,
    capabilities: Any = None,
    list_view: Any = None,
    detail_view: Any = None,
    derived: Any = None,
    predecessors: Any = None,
) -> PluginSchema:
    """Assemble the full ``PluginSchema`` for a model-first plugin.

    Derives the form sections from ``model`` and ``layout`` and the plugin-level
    rules from the model's ``__form_rules__``; the non-form metadata
    (``list_view``, ``capabilities``, ``detail_view``, cascade specs) is supplied
    by the caller because it is not derivable from the create model.

    :param model: The create model carrying the field markers.
    :param layout: The section layout for the create form.
    :param name: The plugin identifier.
    :param display_name: The human-readable plugin title.
    :param description: Optional plugin description. Defaults to ``None``.
    :param task_type: Optional task-type identifier. Defaults to ``None``.
    :param capabilities: Optional plugin capabilities. Defaults to ``None``.
    :param list_view: The list-view configuration (required for task-style
        plugins). Defaults to ``None``.
    :param detail_view: Optional detail-page layout. Defaults to ``None``.
    :param derived: Optional derived-task specs. Defaults to ``None``.
    :param predecessors: Optional predecessor specs. Defaults to ``None``.
    :return: The fully-assembled, validated plugin schema.
    """
    rules = getattr(model, "__form_rules__", FormRules())
    return PluginSchema(
        name=name,
        display_name=display_name,
        description=description,
        task_type=task_type,
        forms=derive_form_sections(model, layout),
        capabilities=capabilities,
        list_view=list_view,
        detail_view=detail_view,
        derived=derived,
        predecessors=predecessors,
        fail_when=list(rules.fail_when) or None,
        cardinality_rules=list(rules.cardinality_rules) or None,
    )


def build_runtime_schema(model: type["AppFormModel"]) -> PluginSchema:
    """Return a single-section ``PluginSchema`` for runtime rule-plan extraction.

    Section-scoped and plugin-scoped rules are hoisted to plugin scope because
    the runtime rule plan is flat — rule placement is irrelevant to evaluation,
    only to the wire layout (which :func:`derive_form_sections` handles).

    :param model: The create model carrying the field markers and rules.
    :return: A schema whose single form section holds every gate-only field.
    """
    fields = _gate_only_fields(model)
    rules = getattr(model, "__form_rules__", FormRules())
    fail_when = list(rules.fail_when)
    cardinality = list(rules.cardinality_rules)
    for section_rules in rules.sections.values():
        fail_when.extend(section_rules.fail_when)
        cardinality.extend(section_rules.cardinality_rules)
    return PluginSchema(
        name="app_form_model_runtime",
        display_name="app_form_model_runtime",
        forms=[FormSection(title="rules", fields=fields)],
        list_view=ListView(columns=[Column(key="name", label="Name")]),
        fail_when=fail_when or None,
        cardinality_rules=cardinality or None,
    )
