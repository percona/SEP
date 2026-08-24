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
:class:`Forbidden`, :class:`Choices`, :class:`Hidden`) are small frozen
dataclasses placed in a field's ``Annotated[...]`` and read back from
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

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import auto, StrEnum
from types import MappingProxyType
from typing import Any

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.rules import (
    CardinalityRule,
    FailRule,
    FieldGate,
    Predicate,
)

__all__ = [
    "ArgFormat",
    "Choices",
    "FieldWidget",
    "Forbidden",
    "FormLayout",
    "FormRules",
    "Hidden",
    "HostRef",
    "Option",
    "RemoteChoices",
    "Requires",
    "SchemaRef",
    "SectionLayout",
    "SectionRules",
    "ServiceRef",
    "TableRef",
    "Ui",
    "find_arg_format",
    "resolve_arg_template",
]


class FieldWidget(StrEnum):
    """Select a presentation widget when the base annotation cannot disambiguate it.

    A plain ``str`` maps to :class:`~app.sep.apps.framework.schema.StringField`
    by default; the multi-line and choice variants are indistinguishable at the
    type level and are chosen explicitly via :attr:`Ui.widget`.
    """

    TEXTAREA = auto()
    YAML = auto()
    CHOICE = auto()
    MULTI_CHOICE = auto()


_UNSET = object()
"""Sentinel marking :attr:`Ui.default` as unset.

``None`` is a legitimate form default, so it cannot double as "unset"; a distinct
module-level object lets the derivation tell "use the Pydantic default" apart from
"the form default is ``None``".
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Ui:
    """Carry a field's presentation metadata; never validation semantics.

    Removing any attribute here cannot change what the server accepts (the
    create model's own type governs that), so per the DSL's governing rule
    presentation extras belong on ``Ui`` while gates live in separate
    :class:`Requires` / :class:`Forbidden` markers.

    :param label: The human-readable field label. Optional; when omitted,
        derived from the field name at consumption (underscores replaced by
        spaces and title-cased). Supply an explicit label only when it diverges
        from that default.
    :param section: The layout-section key the field belongs to; must match a
        :attr:`SectionLayout.key` in the form layout.
    :param description: Optional helper text rendered beneath the field.
    :param depends_on: For a cascade reference (``SchemaRef`` / ``TableRef`` /
        ``HostRef``) or a :class:`RemoteChoices` field, the field name whose
        value drives this field's options or default selection. Required for
        ``SchemaRef`` / ``TableRef``; optional for ``HostRef`` (when set on a
        single-value host field, the renderer auto-selects an executor from the
        upstream service; multi-host ignores it) and for ``RemoteChoices`` (when
        set, the fetch is parameterised by the dependency's value and the field
        stays disabled until it is set, unless the marker's ``allow_custom``
        keeps free-text entry open). Ignored for other field kinds. Defaults
        to ``None``.
    :param order: Sort position within the section; ties break on declaration
        order. Defaults to ``0``.
    :param required: Override for the wire ``required`` flag. ``None`` (the
        default) derives it from whether the model field has a default; set it
        when a field carries a default yet must still render as required.
    :param widget: Optional widget override for cases the base type cannot
        express (multi-line text, YAML, an int/str choice). Defaults to
        ``None`` (infer from the annotation).
    :param default: Tri-state form-display default for the derived schema field,
        distinct from the model/runtime default. Unset (the :data:`_UNSET`
        sentinel, the default) derives the schema default from the Pydantic field
        default; ``None`` sets the form default to ``None``; any other value sets
        the form default to that value. The model's own default — what the JSON
        body validates against — is never affected.
    """

    label: str | None = None
    section: str
    description: str | None = None
    depends_on: str | None = None
    order: int = 0
    required: bool | None = None
    widget: FieldWidget | None = None
    default: Any = _UNSET

    @property
    def has_default(self) -> bool:
        """Return whether a tri-state form default was set (a value or ``None``)."""
        return self.default is not _UNSET


@dataclass(frozen=True, slots=True)
class ArgFormat:
    """Map a field to a CLI argument via a ``${value}`` template.

    Mirrors the ``${value}`` convention used by snippet parameter metadata. A
    *value* arg's template contains ``${value}`` and is emitted — with the field
    value shlex-quoted and substituted in — only when the field value is truthy.
    A *flag* arg's template omits ``${value}`` and is emitted verbatim only when
    the field value is ``True``. The marker is read back from the field's
    ``FieldInfo.metadata`` to assemble the run-command argument string; the
    presence of ``${value}`` is itself the value-vs-flag discriminator, so no
    separate flag attribute is needed.

    Leaving ``template`` unset derives it from the field name and type — a
    non-``bool`` field becomes the value arg ``--<kebab-field-name>=${value}`` and
    a ``bool`` field becomes the flag ``--<kebab-field-name>`` — so a field carries
    an explicit template only when its CLI spelling diverges from its name (a
    ``bool`` ``explain_arg`` field whose flag is ``--explain``, say).

    :param template: The argument template — ``"--databases=${value}"`` for a
        value arg or ``"--binary-index"`` for a flag. Defaults to ``None``, which
        derives ``--<kebab-field-name>=${value}`` for a non-``bool`` field and
        ``--<kebab-field-name>`` for a ``bool`` field.
    """

    template: str | None = None


def find_arg_format(name: str, metadata: list[Any]) -> ArgFormat | None:
    """Return the field's single :class:`ArgFormat` marker, or ``None``.

    :param name: The field name, used in the error message.
    :param metadata: The field's ``FieldInfo.metadata`` list.
    :return: The ``ArgFormat`` marker, or ``None`` when the field declares none.
    :raises ValueError: When the field declares more than one ``ArgFormat`` marker.
    """
    found = [item for item in metadata if isinstance(item, ArgFormat)]
    if len(found) > 1:
        raise ValueError(
            f"field {name!r} declares {len(found)} ArgFormat markers; at most one "
            "is allowed per field"
        )
    return found[0] if found else None


def resolve_arg_template(name: str, annotation: Any, marker: ArgFormat) -> str:
    """Return the field's explicit ``ArgFormat`` template, or derive it from the name.

    A templateless marker (``template is None``) derives the conventional shape from
    the field name and type: a non-``bool`` field becomes the value arg
    ``--<kebab-field-name>=${value}`` and a ``bool`` field becomes the flag
    ``--<kebab-field-name>``. A field declares an explicit template only when its CLI
    spelling diverges from its name.

    :param name: The field name, kebab-cased for the derived template.
    :param annotation: The field's resolved type, selecting the value-vs-flag shape.
    :param marker: The field's ``ArgFormat`` marker.
    :return: The explicit template, or the derived default when none was given.
    """
    if marker.template is not None:
        return marker.template
    flag = "--" + name.replace("_", "-")
    return flag if annotation is bool else f"{flag}=${{value}}"


@dataclass(frozen=True, slots=True)
class Hidden:
    """Mark a field as omitted from the derived schema, kept on the create model.

    A field marked ``Hidden`` is dropped from the derived form sections, so it never
    renders as a form field and needs no :class:`Ui` marker, yet it stays on the
    create model and is validated in the JSON request body. Use it for a
    capability-control field the framework renders from a capability flag (the
    ``alert_on_fail`` pattern), where an explicit form field would duplicate the
    rendered control.
    """


@dataclass(frozen=True, slots=True)
class ServiceRef:
    """Mark a field as an inventory service selector.

    :param service_types: The service types the selector offers.
    :param allow_custom: When ``True``, the field accepts a free-typed value
        alongside the inventory options and emits ``allow_custom`` on the wire.
        Defaults to ``False``.
    :param check_connectivity: When ``True``, the create route runs its
        post-creation connectivity probe against this service, and the service is
        selected as the envelope's primary (``_service_name``, the connectivity
        meta, and the executor-target fallback) even when a second ``ServiceRef``
        resolves. ``check_connectivity`` therefore implies ``primary``. When none
        is marked the sole ``ServiceRef`` is the primary and no probe runs.
        Defaults to ``False``.
    :param primary: When ``True``, the service is the envelope's primary
        (``_service_name``, the connectivity meta, and the executor-target
        fallback) *without* enabling the probe — the way to name a primary among
        several ``ServiceRef`` fields when no connectivity check is wanted. A model
        designates at most one primary across both markers: at most one
        ``ServiceRef`` may be marked ``check_connectivity`` **or** ``primary`` (a
        single field carrying both is redundant, since ``check_connectivity``
        already implies primary). Defaults to ``False``.
    :param multiple: When ``True``, the field is a multi-value selector backed by
        a ``list[...]`` / ``set[...]`` annotation and derives a
        ``MultiServiceField``. Defaults to ``False`` (single-value).
    """

    service_types: tuple[ServiceTypeEnum, ...]
    allow_custom: bool = False
    check_connectivity: bool = False
    primary: bool = False
    multiple: bool = False

    def __post_init__(self) -> None:
        """Normalise ``service_types`` to a tuple so the marker stays hashable."""
        object.__setattr__(self, "service_types", tuple(self.service_types))


@dataclass(frozen=True, slots=True)
class SchemaRef:
    """Mark a field as an inventory database-schema selector.

    The cascade source is declared via ``Ui(depends_on=...)``.

    :param allow_custom: When ``True``, the field also accepts a free-typed
        value and emits ``allow_custom`` on the wire. Defaults to ``False``.
    :param multiple: When ``True``, the field is a multi-value selector backed by
        a ``list[...]`` / ``set[...]`` annotation and derives a
        ``MultiSchemaField``. Defaults to ``False`` (single-value).
    """

    allow_custom: bool = False
    multiple: bool = False


@dataclass(frozen=True, slots=True)
class TableRef:
    """Mark a field as an inventory table selector.

    The cascade source is declared via ``Ui(depends_on=...)``.

    :param allow_custom: When ``True``, the field also accepts a free-typed
        value and emits ``allow_custom`` on the wire. Defaults to ``False``.
    :param multiple: When ``True``, the field is a multi-value selector backed by
        a ``list[...]`` / ``set[...]`` annotation and derives a
        ``MultiTableField``. Defaults to ``False`` (single-value).
    """

    allow_custom: bool = False
    multiple: bool = False


@dataclass(frozen=True, slots=True)
class HostRef:
    """Mark a field as an executor-target (Nomad / Celery) selector.

    Cascade from a service (or other upstream field) is declared via
    ``Ui(depends_on=...)``, the same way :class:`SchemaRef` / :class:`TableRef`
    declare theirs. When set on a single-value field, the derived
    ``HostField`` carries ``depends_on`` on the wire and the renderer may
    auto-select an executor from the upstream value; when omitted the
    selector lists every available executor with no cascade. Multi-value
    (``multiple=True``) may still emit ``depends_on`` on ``MultiHostField``,
    but cascade auto-select is single-host only today.

    ``target_service`` is independent of ``Ui(depends_on=...)``. It names the
    service field whose node address the renderer compares against the selected
    host for a non-blocking co-location warning. Explicit ``target_service``
    configuration is independent of cascade auto-select. When it is omitted,
    derivation falls back to ``Ui(depends_on=...)`` when set, so an existing
    service-driven cascade (e.g. MongoDB Backup) also enables the warning.

    :param allow_custom: When ``True``, the field also accepts a free-typed
        value and emits ``allow_custom`` on the wire. Defaults to ``False``.
    :param multiple: When ``True``, the field is a multi-value selector backed by
        a ``list[...]`` / ``set[...]`` annotation and derives a
        ``MultiHostField``. Defaults to ``False`` (single-value).
    :param target_service: Optional name of the service field used for the
        co-location warning. ``None`` (the default) lets derivation fall back
        to ``Ui(depends_on=...)`` when that is set.
    """

    allow_custom: bool = False
    multiple: bool = False
    target_service: str | None = None


@dataclass(frozen=True, slots=True)
class Option:
    """Represent a single choice option with an optional disabled state.

    Use inside :class:`Choices` when one or more options should be rendered
    non-selectable with an explanatory tooltip.  Bare ``(value, label)`` tuples
    inside :class:`Choices` remain supported and are treated as enabled options.

    :param value: The value submitted when the option is selected. Stringified
        to match :attr:`~app.sep.apps.framework.schema.Choice.value`.
    :param label: The human-readable label displayed for the option.
    :param disabled: When ``True``, the option is rendered non-selectable.
        UI hint only; server-side rejection of disabled values remains the
        consuming app's :class:`~app.sep.apps.framework.rules.FormRules`
        responsibility. Defaults to ``False``.
    :param disabled_reason: Explanatory text surfaced in a tooltip when the
        option is non-selectable. May only be set together with
        ``disabled=True``.
    """

    value: object
    label: str
    disabled: bool = False
    disabled_reason: str | None = None

    def __post_init__(self) -> None:
        """Validate that disabled_reason is only set when disabled is True."""
        if self.disabled_reason is not None and not self.disabled:
            raise ValueError("disabled_reason may only be set when disabled is True")


@dataclass(frozen=True, slots=True)
class Choices:
    """Provide explicit options for a choice field.

    Always wins over type-derived options, and is required for choices whose
    labels are not derivable from the type (an ``int`` rendered as a dropdown,
    a ``Literal`` whose strings carry no display text). Values are stringified
    to match :attr:`~app.sep.apps.framework.schema.Choice.value`.

    Options may be bare ``(value, label)`` tuples or :class:`Option` instances.
    Use :class:`Option` when one or more options should be rendered
    non-selectable (see :attr:`Option.disabled` / :attr:`Option.disabled_reason`).

    :param options: Ordered options; declaration order is the wire order.
        Each entry is either a ``(value, label)`` tuple or an :class:`Option`.
    """

    options: tuple[tuple[object, str] | Option, ...]

    def __post_init__(self) -> None:
        """Normalize options to ``Option`` instances so the marker stays hashable."""
        normalized: list[Option] = []
        for opt in self.options:
            if isinstance(opt, Option):
                normalized.append(opt)
                continue
            try:
                value, label = opt
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Choices options must be Option or (value, label) tuples"
                ) from exc
            normalized.append(Option(value=value, label=label))

        object.__setattr__(
            self,
            "options",
            tuple(normalized),
        )


@dataclass(frozen=True, slots=True)
class RemoteChoices:
    """Mark a field whose options are fetched at render from an app endpoint.

    Unlike :class:`Choices` (static options embedded in the wire), the options
    are fetched at render time from ``endpoint``, which must return a
    ``Choice``-compatible list (``value``, ``label``, optional ``disabled`` /
    ``disabled_reason``). An optional cascade is declared via
    ``Ui(depends_on=...)`` — when set, the fetch is parameterised by the
    dependency's value (passed as a query parameter named after the
    ``depends_on`` field) and the field lists no options until the dependency is
    set, mirroring :class:`SchemaRef` / :class:`TableRef`; it also stays disabled
    while it waits unless ``allow_custom`` keeps free-text entry open. When
    ``depends_on`` is omitted the field fetches once with no cascade (mirroring
    the optional cascade of :class:`HostRef`).

    The annotation must accept ``str``, since a set value (a fetched option's
    ``value`` or a free-typed custom value) reaches the model as a string. An
    **optional** field must additionally accept ``None``, because the selector
    commits ``null`` both when the user clears it and — unprompted — when its
    cascade parent changes; declare those as ``str | None = None``. A required
    field may stay a bare ``str``: the renderer blocks the submit rather than
    sending the ``null``. Derivation rejects either mismatch, so a schema that
    builds cannot 422 on the value its own selector commits.

    :param endpoint: The fully-resolved path the renderer fetches options from,
        relative to the frontend ``apiClient`` base (``/api``). Bake any
        app-specific path segments here at schema-build time (e.g.
        ``/apps/<app_key>/<sub>/<resource>``) rather than templating client-side.

        .. note::
            On a ``TaskExecutionApp`` with the default ``capabilities.detail``,
            ``build_router`` mounts the greedy ``GET /{detail_path_param}``
            before ``extra_routes``, so a **single-segment** sibling path (e.g.
            ``/apps/<key>/choices``) will be swallowed by the detail route and
            return 404. Use at least two path segments after the app prefix
            (e.g. ``/apps/<key>/backups/choices``) to avoid the collision.
    :param allow_custom: When ``True``, the field also accepts a free-typed
        value alongside the fetched options and emits ``allow_custom`` on the
        wire. Defaults to ``False``.
    """

    endpoint: str
    allow_custom: bool = False

    def __post_init__(self) -> None:
        """Reject an empty endpoint so the wire never advertises an unfetchable source."""
        if not self.endpoint.strip():
            raise ValueError("RemoteChoices endpoint must be a non-empty path")


@dataclass(frozen=True, slots=True)
class Requires:
    """Gate a field as required when ``when`` matches (a self-scoped requires gate).

    :param when: The predicate that, when true, requires the field's presence.
    :param message: Optional failure message surfaced when the gate fires.
        Defaults to ``None``.
    """

    when: Predicate
    message: str | None = None


@dataclass(frozen=True, slots=True)
class Forbidden:
    """Gate a field as forbidden when ``when`` matches (a self-scoped forbidden gate).

    :param when: The predicate that, when true, forbids the field's presence.
    :param message: Optional failure message surfaced when the gate fires.
        Defaults to ``None``.
    """

    when: Predicate
    message: str | None = None


@dataclass(frozen=True, slots=True)
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
        :attr:`~app.sep.apps.framework.schema.FormSection.forbidden`. This is
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


#: Shared Task-section layout adopted by every task app's ``FormLayout`` and the
#: task scaffold template. Frozen (see :class:`SectionLayout`), so this single
#: instance is safe to reference directly.
TASK_SECTION_LAYOUT = SectionLayout(key="Task", title="Task")


@dataclass(frozen=True, slots=True)
class FormLayout:
    """Declare a plugin's create-form sections by key.

    :param sections: The section layouts keyed by ``key``; each supplies a
        section's title and non-order metadata (``collapsible``, ``forbidden``,
        ...). The section wire order is derived from field first-appearance on the
        model, not from this tuple's order; every :attr:`Ui.section` must match one
        ``key`` here.
    """

    sections: tuple[SectionLayout, ...]

    def __post_init__(self) -> None:
        """Normalise ``sections`` to a tuple so the layout stays hashable."""
        object.__setattr__(self, "sections", tuple(self.sections))


@dataclass(frozen=True, slots=True)
class SectionRules:
    """Hold the conditional rules scoped to one form section.

    :param fail_when: Predicate-only invariants scoped to the section. Defaults
        to an empty tuple.
    :param cardinality_rules: Cardinality constraints scoped to the section.
        Defaults to an empty tuple.
    """

    fail_when: tuple[FailRule, ...] = ()
    cardinality_rules: tuple[CardinalityRule, ...] = ()


@dataclass(frozen=True, slots=True)
class FormRules:
    """Hold the section-scoped and plugin-scoped conditional rules of a model.

    Field-level gates live on the fields themselves (:class:`Requires` /
    :class:`Forbidden`); this object carries only the rules that cannot attach
    to a single field.

    :param sections: Section-scoped rules keyed by section key. Defaults to an
        empty mapping.
    :param fail_when: App-scoped predicate-only invariants. Defaults to an
        empty tuple.
    :param cardinality_rules: App-scoped cardinality constraints. Defaults to
        an empty tuple.
    """

    sections: Mapping[str, SectionRules] = field(default_factory=dict)
    fail_when: tuple[FailRule, ...] = ()
    cardinality_rules: tuple[CardinalityRule, ...] = ()

    def __post_init__(self) -> None:
        """Freeze ``sections`` so the shared default cannot leak across models."""
        object.__setattr__(self, "sections", MappingProxyType(dict(self.sections)))
