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

"""Declare the annotation markers and layout objects of the model-first form DSL.

The markers (:class:`Ui`, the four reference types, :class:`Requires`,
:class:`Forbidden`, :class:`Choices`) are small frozen dataclasses placed in a
field's ``Annotated[...]`` and read back from
:attr:`pydantic.fields.FieldInfo.metadata`. Pydantic preserves objects it does
not recognise as constraints in that list and ignores them during validation,
so they ride along on the create model without affecting what the server
accepts. The markers must sit at the **outer** ``Annotated`` level wrapping the
full field type — ``Annotated[int | None, SchemaRef(...), Ui(...)]`` — because a
marker nested inside a union member (``Annotated[int, SchemaRef(...)] | None``)
stays buried in the annotation and never reaches ``FieldInfo.metadata``.

The layout objects (:class:`SectionLayout`, :class:`FormLayout`,
:class:`SectionRules`, :class:`FormRules`) are ordinary objects passed to the
derivation functions, not annotation metadata.
"""

from dataclasses import dataclass, field
from enum import auto, StrEnum

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework.rules import (
    CardinalityRule,
    FailRule,
    FieldGate,
    Predicate,
)

__all__ = [
    "Choices",
    "FieldWidget",
    "Forbidden",
    "FormLayout",
    "FormRules",
    "HostRef",
    "Requires",
    "SchemaRef",
    "SectionLayout",
    "SectionRules",
    "ServiceRef",
    "TableRef",
    "Ui",
]


class FieldWidget(StrEnum):
    """Select a presentation widget when the base annotation cannot disambiguate it.

    A plain ``str`` maps to :class:`~app.sep.plugins.framework.schema.StringField`
    by default; the multi-line and choice variants are indistinguishable at the
    type level and are chosen explicitly via :attr:`Ui.widget`.
    """

    TEXTAREA = auto()
    YAML = auto()
    CHOICE = auto()
    MULTI_CHOICE = auto()


@dataclass(frozen=True)
class Ui:
    """Carry a field's presentation metadata; never validation semantics.

    Removing any attribute here cannot change what the server accepts (the
    create model's own type governs that), so per the DSL's governing rule
    presentation extras belong on ``Ui`` while gates live in separate
    :class:`Requires` / :class:`Forbidden` markers.

    :param label: The human-readable field label.
    :param section: The layout-section key the field belongs to; must match a
        :attr:`SectionLayout.key` in the form layout.
    :param description: Optional helper text rendered beneath the field.
    :param depends_on: For a cascade reference (``SchemaRef`` / ``TableRef``),
        the field name whose value drives this field's options. Required for
        those refs; ignored otherwise. Defaults to ``None``.
    :param order: Sort position within the section; ties break on declaration
        order. Defaults to ``0``.
    :param required: Override for the wire ``required`` flag. ``None`` (the
        default) derives it from whether the model field has a default; set it
        when a field carries a default yet must still render as required.
    :param widget: Optional widget override for cases the base type cannot
        express (multi-line text, YAML, an int/str choice). Defaults to
        ``None`` (infer from the annotation).
    """

    label: str
    section: str
    description: str | None = None
    depends_on: str | None = None
    order: int = 0
    required: bool | None = None
    widget: FieldWidget | None = None


@dataclass(frozen=True)
class ServiceRef:
    """Mark a field as an inventory service selector.

    :param service_types: The service types the selector offers.
    :param allow_custom: When ``True``, the field accepts a free-typed value
        alongside the inventory options and emits ``allow_custom`` on the wire.
        Defaults to ``False``.
    """

    service_types: tuple[ServiceTypeEnum, ...]
    allow_custom: bool = False

    def __post_init__(self) -> None:
        """Normalise ``service_types`` to a tuple so the marker stays hashable."""
        object.__setattr__(self, "service_types", tuple(self.service_types))


@dataclass(frozen=True)
class SchemaRef:
    """Mark a field as an inventory database-schema selector.

    The cascade source is declared via ``Ui(depends_on=...)``.

    :param allow_custom: When ``True``, the field also accepts a free-typed
        value and emits ``allow_custom`` on the wire. Defaults to ``False``.
    """

    allow_custom: bool = False


@dataclass(frozen=True)
class TableRef:
    """Mark a field as an inventory table selector.

    The cascade source is declared via ``Ui(depends_on=...)``.

    :param allow_custom: When ``True``, the field also accepts a free-typed
        value and emits ``allow_custom`` on the wire. Defaults to ``False``.
    """

    allow_custom: bool = False


@dataclass(frozen=True)
class HostRef:
    """Mark a field as an executor-target (Nomad / Celery) selector.

    :param allow_custom: When ``True``, the field also accepts a free-typed
        value and emits ``allow_custom`` on the wire. Defaults to ``False``.
    """

    allow_custom: bool = False


@dataclass(frozen=True)
class Choices:
    """Provide explicit ``(value, label)`` options for a choice field.

    Always wins over type-derived options, and is required for choices whose
    labels are not derivable from the type (an ``int`` rendered as a dropdown,
    a ``Literal`` whose strings carry no display text). Values are stringified
    to match :attr:`~app.sep.plugins.framework.schema.Choice.value`.

    :param options: Ordered ``(value, label)`` pairs; declaration order is the
        wire order.
    """

    options: tuple[tuple[object, str], ...]

    def __post_init__(self) -> None:
        """Normalise options to a tuple of pairs so the marker stays hashable."""
        object.__setattr__(
            self, "options", tuple((value, label) for value, label in self.options)
        )


@dataclass(frozen=True)
class Requires:
    """Gate a field as required when ``when`` matches (a self-scoped requires gate).

    :param when: The predicate that, when true, requires the field's presence.
    :param message: Optional failure message surfaced when the gate fires.
        Defaults to ``None``.
    """

    when: Predicate
    message: str | None = None


@dataclass(frozen=True)
class Forbidden:
    """Gate a field as forbidden when ``when`` matches (a self-scoped forbidden gate).

    :param when: The predicate that, when true, forbids the field's presence.
    :param message: Optional failure message surfaced when the gate fires.
        Defaults to ``None``.
    """

    when: Predicate
    message: str | None = None


@dataclass(frozen=True)
class SectionLayout:
    """Declare one section's presentation in a :class:`FormLayout`.

    :param key: The section key referenced by :attr:`Ui.section`.
    :param title: The section heading.
    :param description: Optional helper text beneath the heading. Defaults to
        ``None``.
    :param collapsible: Whether the renderer may collapse the section. Defaults
        to ``False``.
    :param collapsed_by_default: Whether a collapsible section starts collapsed.
        Defaults to ``False``.
    :param render_after_submit: Whether the section renders after the submit
        button. Defaults to ``False``.
    :param forbidden: Optional whole-section hide gates copied verbatim to
        :attr:`~app.sep.plugins.framework.schema.FormSection.forbidden`. This is
        a presentation gate, not a runtime rule. Defaults to ``None``.
    """

    key: str
    title: str
    description: str | None = None
    collapsible: bool = False
    collapsed_by_default: bool = False
    render_after_submit: bool = False
    forbidden: tuple[FieldGate, ...] | None = None

    def __post_init__(self) -> None:
        """Normalise ``forbidden`` to a tuple so the layout stays hashable."""
        if self.forbidden is not None:
            object.__setattr__(self, "forbidden", tuple(self.forbidden))


@dataclass(frozen=True)
class FormLayout:
    """Declare the ordered sections of a plugin's create form.

    :param sections: The ordered section layouts; section order is the wire
        order, and every :attr:`Ui.section` must match one ``key`` here.
    """

    sections: tuple[SectionLayout, ...]

    def __post_init__(self) -> None:
        """Normalise ``sections`` to a tuple so the layout stays hashable."""
        object.__setattr__(self, "sections", tuple(self.sections))


@dataclass(frozen=True)
class SectionRules:
    """Hold the conditional rules scoped to one form section.

    :param fail_when: Predicate-only invariants scoped to the section. Defaults
        to an empty tuple.
    :param cardinality_rules: Cardinality constraints scoped to the section.
        Defaults to an empty tuple.
    """

    fail_when: tuple[FailRule, ...] = ()
    cardinality_rules: tuple[CardinalityRule, ...] = ()


@dataclass(frozen=True)
class FormRules:
    """Hold the section-scoped and plugin-scoped conditional rules of a model.

    Field-level gates live on the fields themselves (:class:`Requires` /
    :class:`Forbidden`); this object carries only the rules that cannot attach
    to a single field.

    :param sections: Section-scoped rules keyed by section key. Defaults to an
        empty mapping.
    :param fail_when: Plugin-scoped predicate-only invariants. Defaults to an
        empty tuple.
    :param cardinality_rules: Plugin-scoped cardinality constraints. Defaults to
        an empty tuple.
    """

    sections: dict[str, SectionRules] = field(default_factory=dict)
    fail_when: tuple[FailRule, ...] = ()
    cardinality_rules: tuple[CardinalityRule, ...] = ()
