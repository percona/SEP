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

"""Classification registry and field-introspection helpers for setting overrides."""

from __future__ import annotations

__all__ = [
    "NESTED_VALUE_MISSING",
    "REMOTE_API_TLS_MARKERS",
    "SECRET_STR_MASK",
    "FieldMarkerKey",
    "FieldMarkers",
    "FieldMetadata",
    "InheritedMarkers",
    "Materializer",
    "MaterializerContext",
    "MaterializerPurpose",
    "ReloadClassification",
    "canonical_override_key",
    "chain_has_advanced",
    "chain_has_explicit_not_overridable",
    "chain_is_locked",
    "coerce_field_value",
    "coerce_nested_field_value",
    "dump_field_value",
    "field_materializer",
    "field_reload_classification",
    "hot_field",
    "hot_field_names",
    "is_advanced_field",
    "is_explicit_not_overridable",
    "is_hot_reloadable",
    "is_nested_overridable_parent",
    "iter_class_fields",
    "iter_nested_leaf_keys",
    "materialize_override_value",
    "materialize_template",
    "materialize_via_owning_model",
    "nested_overridable_field",
    "nested_overridable_field_names",
    "not_overridable_field",
    "override_keys_for_rows",
    "preserve_patch_credential_url_value",
    "rendered_leaf_keys",
    "resolve_nested_field",
    "resolve_nested_field_metadata",
    "resolve_nested_value",
    "unwrap_secrets_for_storage",
]

import functools
import typing
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from string import Template
from types import UnionType
from typing import Annotated, Any, NamedTuple, TYPE_CHECKING, TypedDict, Union

from pydantic import BaseModel, SecretBytes, SecretStr, TypeAdapter, WrapSerializer
from pydantic.errors import PydanticSchemaGenerationError
from pydantic_core import PydanticUndefined

from app.core.settings_override.models import SettingClassEnum, SettingOverride
from app.core.settings_override.policy import (
    has_allowed_key_under,
    is_key_allowed,
    is_restriction_active,
)
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.utils.fields import (
    _credential_url_serializer,
    preserve_credential_url_password,
)
from app.core.utils.pydantic import (
    annotation_pydantic_class,
    CustomFieldMetadata,
    field_with_metadata,
)

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

    # Imported only for annotations: the override substrate must not depend on
    # the concrete settings classes at runtime, which lets ``app.core.config``
    # import this module at top level without a circular import.
    from app.core.config import BaseYamlSettings

#: Sentinel returned by :func:`resolve_nested_value` when a segment along the
#: chain is absent. Distinct from a present intermediate or leaf whose value is
#: ``None`` (an optional intermediate collapsing to ``None``, or an unresolved
#: secret leaf). The LIST response builder maps this to a JSON ``null``.
NESTED_VALUE_MISSING = object()


class ReloadClassification(StrEnum):
    """Declare the reload behavior of an overridable settings field.

    :cvar HOT: Field can be overridden via a DB row and the new value takes
        effect on the next snapshot refresh, without restarting the service.
        For a nested-model field, ``HOT`` permits both whole-object override
        (``PATCH {parent: {...}}``) and per-child override (``parent__leaf``).
    :vartype HOT: str
    :cvar NESTED_ONLY: Nested-model field whose children may be overridden
        (``parent__leaf``) while the parent itself rejects whole-object
        override (``PATCH {parent: {...}}`` → 422). Children default to
        HOT-inherit unless explicitly marked :func:`not_overridable_field`.
    :vartype NESTED_ONLY: str
    :cvar NOT_OVERRIDABLE: Field is not overridable from the database; YAML
        and environment variables remain the only sources of truth.
    :vartype NOT_OVERRIDABLE: str
    """

    HOT = "hot"
    NESTED_ONLY = "nested_only"
    NOT_OVERRIDABLE = "not_overridable"


class FieldMarkerKey(StrEnum):
    """Name the metadata-channel keys carrying a field's classification markers.

    A single definition for the marker vocabulary the override substrate reads
    and writes, so the keys are not repeated as bare string literals across the
    construction helpers (:func:`hot_field` and friends) and the ``.get(...)``
    read sites. As a :class:`~enum.StrEnum` each member *is* its string value,
    so it interoperates with dict keys typed as the plain literals below.

    :cvar RELOAD: The :class:`ReloadClassification` channel.
    :vartype RELOAD: str
    :cvar ADVANCED: The display-only ``advanced`` UI-grouping flag channel.
    :vartype ADVANCED: str
    :cvar MATERIALIZER: The optional snapshot :data:`Materializer` channel.
    :vartype MATERIALIZER: str
    """

    RELOAD = "reload"
    ADVANCED = "advanced"
    MATERIALIZER = "materializer"


class MaterializerPurpose(StrEnum):
    """Name why a materializer is running, so read and write may diverge.

    A materializer that cross-checks its payload against state the deployment
    holds elsewhere needs both verdicts. Rejecting a payload submitted now
    against state it does not match is a client error. A row stored earlier
    against state that has since changed is a deployment condition the operator
    has to be told about, and raising there only drops the row and erases the
    evidence.

    :cvar VALIDATE: A payload submitted through the settings API right now.
    :cvar SNAPSHOT: A row stored earlier, being read back into a snapshot.
    """

    VALIDATE = "validate"
    SNAPSHOT = "snapshot"


class MaterializerContext(NamedTuple):
    """Bundle the inputs a snapshot materializer may consult.

    A materializer receives the whole context and uses only the members it
    needs. :func:`app.core.settings_override.cache.build_snapshot` constructs
    one per overridden HOT field whose declaration attached a materializer,
    instead of calling :func:`coerce_field_value` directly.

    :param settings_cls: The Pydantic settings class that owns the field.
    :param field_name: The name of the field being materialized.
    :param field_info: The Pydantic field metadata for the field.
    :param raw: The raw, JSON-decoded value stored on the override row.
    :param purpose: Whether the value is a payload submitted now or a row
        stored earlier. Defaults to the strict :attr:`MaterializerPurpose.VALIDATE`
        so a materializer that ignores it keeps write-time semantics on both
        paths.
    """

    settings_cls: type[BaseYamlSettings]
    field_name: str
    field_info: FieldInfo
    raw: Any
    purpose: MaterializerPurpose = MaterializerPurpose.VALIDATE


Materializer = Callable[[MaterializerContext], Any]


class FieldMarkers(TypedDict, total=False):
    """Type the marker dict a single field carries or an overlay assigns to one.

    Every key is optional (``total=False``): a field or overlay entry supplies
    only the markers it wants set. Typing overlay literals against this (via
    :data:`InheritedMarkers`) gives their keys and values static checking at
    their declaration sites.

    :cvar reload: The field's reload classification.
    :vartype reload: ReloadClassification
    :cvar advanced: Whether the field is display-only ``advanced`` for UI grouping.
    :vartype advanced: bool
    :cvar materializer: The snapshot materializer to run for the field.
    :vartype materializer: Materializer
    """

    reload: ReloadClassification
    advanced: bool
    materializer: Materializer


def hot_field(
    default: Any,
    *,
    materializer: Materializer | None = None,
    advanced: bool = False,
    **kwargs: Any,
) -> FieldInfo:
    """Declare a settings field as HOT-reloadable from a DB override.

    Thin wrapper over :func:`app.core.utils.pydantic.field_with_metadata` that
    attaches ``{"reload": ReloadClassification.HOT}`` so the field is picked up
    by :func:`is_hot_reloadable` and snapshot building. When ``materializer`` is
    supplied it rides the same metadata channel under the ``"materializer"`` key
    and :func:`app.core.settings_override.cache.build_snapshot` invokes it in
    place of the default :func:`coerce_field_value` coercion -- used for fields
    whose snapshot value cannot be produced by a plain ``TypeAdapter`` (a
    before-validator must run, or the type is not Pydantic-serialisable). When
    ``advanced`` is set it
    rides the same channel under the ``"advanced"`` key, read back by
    :func:`is_advanced_field`; it is display-only metadata and does not affect
    override eligibility.

    :param default: The field's default value, passed positionally to ``Field``.
    :type default: Any
    :param materializer: An optional callable that converts the raw override
        value into the snapshot value. Receives a :class:`MaterializerContext`.
    :type materializer: Materializer | None
    :param advanced: Whether to flag the field as ``advanced`` for UI grouping.
    :param kwargs: Additional keyword arguments forwarded to ``Field``.
    :type kwargs: Any
    :return: A Pydantic field marked with the HOT reload classification.
    :rtype: FieldInfo
    """
    metadata = {
        FieldMarkerKey.RELOAD: ReloadClassification.HOT,
        **(
            {FieldMarkerKey.MATERIALIZER: materializer}
            if materializer is not None
            else {}
        ),
        **({FieldMarkerKey.ADVANCED: True} if advanced else {}),
    }
    return field_with_metadata(default, metadata=metadata, **kwargs)


#: Opt-in class attribute mapping an inherited field name to a marker dict, so a
#: subclass can mark inherited fields without redeclaring them. Keys match the
#: field metadata channel (``"reload"``, ``"advanced"``, ``"materializer"``).
INHERITED_MARKERS_ATTR = "INHERITED_MARKERS"

#: Type of an :data:`INHERITED_MARKERS_ATTR` overlay: field name -> marker dict.
#: The outer mapping is read-only (covariant) -- the right shape for a
#: class-level overlay that is only ever read -- while each value is a
#: :class:`FieldMarkers` so overlay literals get key/value checking.
InheritedMarkers = Mapping[str, FieldMarkers]

#: Shared overlay marking the inherited ``BaseRemoteAPI`` TLS fields HOT and
#: ``advanced``, so every remote-api settings model reuses one definition
#: instead of restating it. Lives in the settings-override layer (not on
#: ``BaseRemoteAPI``) to keep ``app.core.requests`` free of any dependency on
#: ``settings_override``.
REMOTE_API_TLS_MARKERS: InheritedMarkers = {
    "verify_ssl": {"reload": ReloadClassification.HOT, "advanced": True},
    "ssl_cafile": {"reload": ReloadClassification.HOT, "advanced": True},
    "ssl_keyfile": {"reload": ReloadClassification.HOT, "advanced": True},
    "ssl_certfile": {"reload": ReloadClassification.HOT, "advanced": True},
}


def _effective_field_markers(
    field_info: FieldInfo,
    owner_cls: type[BaseModel] | None = None,
    field_name: str | None = None,
) -> dict[str, Any]:
    """Return a field's effective markers: its own metadata plus the owner's overlay.

    The field's own metadata takes precedence -- the ``INHERITED_MARKERS_ATTR``
    overlay only fills keys the field does not already carry, so it can *add*
    markers to an inherited field but never un-mark an explicit declaration.

    :param field_info: The Pydantic field metadata to read.
    :param owner_cls: The class that owns ``field_info``, if known.
    :param field_name: The field's attribute name on ``owner_cls``, if known.
    :return: The field's effective markers keyed by marker name.
    """
    markers = CustomFieldMetadata.field_to_dict(field_info)
    if owner_cls is None or field_name is None:
        return markers
    overlay = getattr(owner_cls, INHERITED_MARKERS_ATTR, None)
    if not isinstance(overlay, Mapping):
        return markers
    entry = overlay.get(field_name)
    if not isinstance(entry, Mapping):
        return markers
    return {**entry, **markers}


def _setting_class_or_none(settings_cls: type[BaseModel]) -> SettingClassEnum | None:
    """Return the override-table identifier for a settings class, if it has one.

    Every class a settings router exposes is an enum member, so ``None`` means
    the class can carry no override row at all. Each policy gate reads that as
    "withhold", closing rather than widening the overridable surface.

    :param settings_cls: The Pydantic settings class to identify.
    :return: The matching enum member, or ``None`` when the class has none.
    """
    try:
        return SettingClassEnum(settings_cls.__name__)
    except ValueError:
        return None


def _policy_locked(settings_cls: type[BaseModel], canonical_key: str) -> bool:
    """Return whether ``SETTINGS_OVERRIDE.ALLOWED_KEYS`` withholds one canonical key.

    :param settings_cls: The top-level Pydantic settings class owning the key.
    :param canonical_key: The canonical override key: a top-level field name or
        a ``__``-delimited nested path in its case-corrected spelling.
    :return: ``True`` when a restriction is active and does not allow this pair.
    """
    if not is_restriction_active():
        return False
    setting_class = _setting_class_or_none(settings_cls)
    if setting_class is None:
        return True
    return not is_key_allowed(setting_class, canonical_key)


def is_hot_reloadable(
    settings_cls: type[BaseModel],
    field_name: str,
    *,
    include_policy_gate: bool = True,
) -> bool:
    """Return whether the given field is marked HOT on the given settings class.

    Accepts any Pydantic ``BaseModel`` subclass, not just ``BaseYamlSettings``:
    the nested-override resolver consults this predicate against nested
    submodels (e.g. ``CookieOptions``) when classifying leaf fields.

    The policy gate, however, only answers for a top-level settings class: it
    keys the allowlist on the class ``__name__`` and the key as spelled, and a
    submodel is named by no entry, so the gate withholds it unconditionally.
    Pass ``include_policy_gate=False`` when inspecting a submodel, or ask
    :func:`chain_is_locked` with the top-level class and the full
    ``__``-delimited key instead.

    :param settings_cls: The Pydantic model class to inspect.
    :param field_name: The name of the field to check.
    :param include_policy_gate: Whether to also require
        ``SETTINGS_OVERRIDE.ALLOWED_KEYS`` to permit the key. Pass ``False`` to
        read the static declaration alone, which is what distinguishes a field
        the allowlist withholds from one the code declares not overridable, and
        which is required when ``settings_cls`` is a submodel.
    :return: ``True`` when ``field_name`` exists on ``settings_cls``, is
        marked with ``{"reload": ReloadClassification.HOT}`` via
        :func:`app.core.utils.pydantic.field_with_metadata` or the class overlay,
        and (unless ``include_policy_gate`` is ``False``) the allowlist permits
        overriding it.
    """
    field = settings_cls.model_fields.get(field_name)
    if field is None:
        return False
    markers = _effective_field_markers(
        field, owner_cls=settings_cls, field_name=field_name
    )
    if markers.get(FieldMarkerKey.RELOAD) != ReloadClassification.HOT:
        return False
    return not (include_policy_gate and _policy_locked(settings_cls, field_name))


def field_reload_classification(
    field_info: FieldInfo,
    *,
    owner_cls: type[BaseModel] | None = None,
    field_name: str | None = None,
) -> ReloadClassification:
    """Return the reload classification attached to a single field.

    Reads the ``{"reload": ...}`` metadata set by :func:`hot_field`,
    :func:`nested_overridable_field`, or :func:`not_overridable_field`. Any
    field with no recognised marker is reported ``NOT_OVERRIDABLE``.

    Unlike :func:`is_hot_reloadable` (which takes a settings class plus a field
    name), this operates on a :class:`FieldInfo` directly so callers can
    classify a nested leaf resolved out of a submodel.

    When both ``owner_cls`` and ``field_name`` are supplied
    ``SETTINGS_OVERRIDE.ALLOWED_KEYS`` is consulted too, so a field it withholds
    reports ``NOT_OVERRIDABLE`` and the settings API describes what it will
    actually accept. That lookup only answers for a top-level settings class,
    and this function exposes no way to skip it alone: omitting ``owner_cls`` /
    ``field_name`` drops the class overlay along with it. Classify a submodel
    leaf through :func:`chain_is_locked` instead, passing the top-level class
    and the full ``__``-delimited key.

    :param field_info: The Pydantic field metadata to classify.
    :param owner_cls: The class owning ``field_info``, for overlay lookup.
    :param field_name: The field's name on ``owner_cls``, for overlay lookup.
    :return: The field's reload classification.
    """
    value = _effective_field_markers(field_info, owner_cls, field_name).get(
        FieldMarkerKey.RELOAD
    )
    if value not in {ReloadClassification.HOT, ReloadClassification.NESTED_ONLY}:
        return ReloadClassification.NOT_OVERRIDABLE
    if (
        owner_cls is not None
        and field_name is not None
        and _policy_locked(owner_cls, field_name)
    ):
        return ReloadClassification.NOT_OVERRIDABLE
    return value


def is_explicit_not_overridable(
    field_info: FieldInfo,
    *,
    owner_cls: type[BaseModel] | None = None,
    field_name: str | None = None,
) -> bool:
    """Return whether a field carries an *explicit* ``NOT_OVERRIDABLE`` marker.

    Distinct from ``field_reload_classification(...) == NOT_OVERRIDABLE``: an
    unmarked field reports ``NOT_OVERRIDABLE`` from
    :func:`field_reload_classification` (the default top-level classification),
    but a *nested leaf* under a nested-overridable parent inherits HOT unless it
    is explicitly :func:`not_overridable_field`-marked. This predicate is
    ``True`` only for the explicit marker, so unmarked nested leaves stay
    overridable.

    :param field_info: The Pydantic field metadata to inspect.
    :param owner_cls: The class owning ``field_info``, for overlay lookup.
    :param field_name: The field's name on ``owner_cls``, for overlay lookup.
    :return: ``True`` iff the field has an explicit ``NOT_OVERRIDABLE`` marker.
    :rtype: bool
    """
    return (
        _effective_field_markers(field_info, owner_cls, field_name).get(
            FieldMarkerKey.RELOAD
        )
        == ReloadClassification.NOT_OVERRIDABLE
    )


def hot_field_names(settings_cls: type[BaseYamlSettings]) -> frozenset[str]:
    """Return the set of field names on ``settings_cls`` marked HOT.

    :param settings_cls: The Pydantic settings class to inspect.
    :type settings_cls: type[BaseYamlSettings]
    :return: A frozenset of field names declared HOT via
        :func:`app.core.utils.pydantic.field_with_metadata`.
    :rtype: frozenset[str]
    """
    return frozenset(
        name
        for name in settings_cls.model_fields
        if is_hot_reloadable(settings_cls, name)
    )


def _annotated_type(field_info: FieldInfo) -> Any:
    """Reassemble the constraint-preserving annotated type for a field.

    Constraint metadata attached to the field's annotation (e.g. ``Gt(0)`` from
    ``PositiveInt``) is preserved by re-assembling an ``Annotated`` type from
    ``field_info.annotation`` plus every non-:class:`CustomFieldMetadata` item
    in ``field_info.metadata``. Without this, ``TypeAdapter(field_info.annotation)``
    would accept values the original settings model rejects -- e.g. a negative
    integer override for a ``PositiveInt`` field would silently load.

    :param field_info: The Pydantic field metadata for the target attribute.
    :type field_info: FieldInfo
    :return: The field's annotation, wrapped in ``Annotated`` together with its
        preserved constraint metadata when any constraints are present.
    :rtype: Any
    """
    constraints = tuple(
        item
        for item in field_info.metadata
        if not isinstance(item, CustomFieldMetadata)
    )
    if constraints:
        return Annotated[(field_info.annotation, *constraints)]
    return field_info.annotation


def _coerce_value(field_info: FieldInfo, raw: Any) -> Any:
    """Coerce a raw JSON-decoded value to the field's declared Python type.

    :param field_info: The Pydantic field metadata for the target attribute.
    :type field_info: FieldInfo
    :param raw: The JSON-decoded value as stored on the override row.
    :type raw: Any
    :return: The validated Python value matching ``field_info.annotation``
        plus its preserved constraint metadata.
    :rtype: Any
    :raises ValidationError: If ``raw`` cannot be coerced to the declared
        type or violates a preserved constraint. Callers handle and log.
    """
    return TypeAdapter(_annotated_type(field_info)).validate_python(raw)


def coerce_field_value(field_info: FieldInfo, raw: Any) -> Any:
    """Validate and coerce a raw value to the field's declared annotated type.

    Mirrors the validation that :func:`app.core.settings_override.cache.build_snapshot`
    performs when materialising a DB-override row into a typed Python value,
    including preservation of constraint metadata (``PositiveInt`` etc.) via
    the ``_annotated_type`` reassembly.

    :param field_info: The Pydantic field metadata for the target attribute.
    :type field_info: FieldInfo
    :param raw: The raw, JSON-decoded value to validate and coerce.
    :type raw: Any
    :return: The validated Python value matching the field's annotation plus
        its preserved constraint metadata.
    :rtype: Any
    :raises ValidationError: If ``raw`` cannot be coerced or violates a
        preserved constraint. Callers in the API layer map this to HTTP 422.
    """
    return _coerce_value(field_info, raw)


def field_materializer(
    settings_cls: type[BaseYamlSettings], field_name: str
) -> Materializer | None:
    """Return the materializer declared on a field, or ``None`` if none.

    Reads the ``"materializer"`` entry attached by :func:`hot_field` through the
    same custom-metadata channel :func:`is_hot_reloadable` reads ``"reload"`` from.

    :param settings_cls: The Pydantic settings class to inspect.
    :type settings_cls: type[BaseYamlSettings]
    :param field_name: The name of the field to check.
    :type field_name: str
    :return: The declared :data:`Materializer`, or ``None`` when the field is
        unknown or declares no materializer.
    :rtype: Materializer | None
    """
    field = settings_cls.model_fields.get(field_name)
    if field is None:
        return None
    markers = _effective_field_markers(
        field, owner_cls=settings_cls, field_name=field_name
    )
    return markers.get(FieldMarkerKey.MATERIALIZER)


def is_advanced_field(
    field_info: FieldInfo,
    *,
    owner_cls: type[BaseModel] | None = None,
    field_name: str | None = None,
) -> bool:
    """Return whether a field is flagged ``advanced`` via field metadata.

    Reads the ``"advanced"`` entry attached by :func:`hot_field`,
    :func:`nested_overridable_field`, or :func:`not_overridable_field` through
    the same custom-metadata channel :func:`field_reload_classification` reads
    ``"reload"`` from. ``advanced`` is display-only metadata used by the settings
    UI to group rarely-changed, easy-to-misconfigure settings separately; it does
    not affect override, PATCH, or DELETE eligibility. Operates on a
    :class:`FieldInfo` directly so callers can classify a nested leaf resolved
    out of a submodel.

    :param field_info: The Pydantic field metadata to inspect.
    :param owner_cls: The class owning ``field_info``, for overlay lookup.
    :param field_name: The field's name on ``owner_cls``, for overlay lookup.
    :return: ``True`` iff the field carries an explicit ``advanced`` marker.
    """
    return (
        _effective_field_markers(field_info, owner_cls, field_name).get(
            FieldMarkerKey.ADVANCED, False
        )
        is True
    )


def materialize_via_owning_model(ctx: MaterializerContext) -> Any:
    """Materialize a value by validating it through its owning settings class.

    Runs the owning class's ``mode="before"`` validators (which a bare
    ``TypeAdapter`` on the field annotation would not invoke) by validating a
    single-key payload and reading the resulting attribute back. Only valid for
    settings classes whose every other field is defaulted, so a one-key
    ``model_validate`` succeeds.

    :param ctx: The materialization context.
    :type ctx: MaterializerContext
    :return: The materialized value as the owning model produces it.
    :rtype: Any
    :raises ValidationError: If the owning model rejects the one-key payload.
    :raises ValueError: If a ``mode="before"`` validator rejects ``raw``.
    """
    validated = ctx.settings_cls.model_validate({ctx.field_name: ctx.raw})
    return getattr(validated, ctx.field_name)


def materialize_template(ctx: MaterializerContext) -> Any:
    """Materialize a :class:`string.Template` from a raw string override.

    ``TypeAdapter(Template)`` raises :class:`PydanticSchemaGenerationError`, so a
    ``Template`` field cannot use the default coercion path. A raw string is
    wrapped in a ``Template``; an already-``Template`` value passes through. Any
    other type is rejected -- otherwise a non-string override (e.g. ``1``) would
    be published into the snapshot and crash the next ``safe_substitute`` read
    with ``AttributeError``.

    :param ctx: The materialization context.
    :type ctx: MaterializerContext
    :return: A :class:`string.Template` for the override.
    :rtype: Any
    :raises ValueError: If ``raw`` is neither a string nor a ``Template``.
    """
    if isinstance(ctx.raw, Template):
        return ctx.raw
    if isinstance(ctx.raw, str):
        return Template(ctx.raw)
    raise ValueError(
        f"{ctx.field_name} override must be a string, got {type(ctx.raw).__name__}"
    )


def materialize_override_value(
    settings_cls: type[BaseYamlSettings],
    field_name: str,
    field_info: FieldInfo,
    raw: Any,
    *,
    purpose: MaterializerPurpose = MaterializerPurpose.VALIDATE,
) -> Any:
    """Turn a raw override value into its typed snapshot value.

    Routes through the field's declared materializer when present, otherwise the
    default :func:`coerce_field_value` coercion. Shared by snapshot building
    (:func:`app.core.settings_override.cache.build_snapshot`) and the settings
    API PATCH validation so both accept exactly the same override payloads -- a
    materializer-backed field (``PROVIDERS``, ``FOOTER_TEMPLATE``)
    would otherwise be accepted on snapshot load but rejected by the API.

    ``purpose`` is the one channel through which the two paths may diverge, and
    the snapshot builder is the only caller that sets it. Every materializer
    that ignores it is therefore unaffected.

    :param settings_cls: The Pydantic settings class that owns the field.
    :param field_name: The name of the field being materialized.
    :param field_info: The Pydantic field metadata for the field.
    :param raw: The raw, JSON-decoded override value.
    :param purpose: Whether ``raw`` is a payload submitted now or a row stored
        earlier.
    :return: The materialized (or coerced) typed value.
    :raises ValidationError: If coercion or the materializer's validation fails.
    :raises ValueError: If a ``mode="before"`` validator rejects ``raw``.
    """
    materializer = field_materializer(settings_cls, field_name)
    if materializer is not None:
        return materializer(
            MaterializerContext(settings_cls, field_name, field_info, raw, purpose)
        )
    return coerce_field_value(field_info, raw)


def nested_overridable_field(
    default: Any, *, advanced: bool = False, **kwargs: Any
) -> FieldInfo:
    """Declare a nested-model field whose children may be overridden by DB rows.

    The parent field itself rejects whole-object override
    (``PATCH {parent: {...}}`` → 422). Nested children (``parent__leaf``) are
    accepted, defaulting to HOT-inherit unless the leaf is explicitly
    :func:`not_overridable_field`-marked.

    Mirrors :func:`hot_field`'s call signature; attaches
    ``{"reload": ReloadClassification.NESTED_ONLY}``. When ``advanced`` is set,
    the parent carries an ``advanced`` marker that every emitted leaf inherits
    via :func:`chain_has_advanced` -- the parent's per-leaf expansion would
    otherwise never surface the flag for the session/security-header fields.

    :param default: The field's default value, passed positionally to ``Field``.
    :type default: Any
    :param advanced: Whether to flag the field (and its leaves) as ``advanced``.
    :param kwargs: Additional keyword arguments forwarded to ``Field``.
    :type kwargs: Any
    :return: A Pydantic field marked NESTED_ONLY.
    :rtype: FieldInfo
    """
    metadata = {
        FieldMarkerKey.RELOAD: ReloadClassification.NESTED_ONLY,
        **({FieldMarkerKey.ADVANCED: True} if advanced else {}),
    }
    return field_with_metadata(default, metadata=metadata, **kwargs)


def not_overridable_field(
    default: Any, *, advanced: bool = False, **kwargs: Any
) -> FieldInfo:
    """Declare a settings field as explicitly NOT overridable from a DB row.

    Mirrors :func:`hot_field` but attaches
    ``{"reload": ReloadClassification.NOT_OVERRIDABLE}``. Use under a HOT or
    NESTED_ONLY parent when a specific nested leaf must NOT inherit the
    parent's HOT-by-default child semantics, or on a top-level field that must
    stay environment- and YAML-only -- a whole-object PATCH and every
    ``__``-delimited leaf PATCH are both rejected, so a block whose validity
    depends on cross-field validation is never assembled one leaf at a time.
    ``advanced`` rides the same channel as on the other helpers and is
    independent of the reload classification.

    :param default: The field's default value, passed positionally to ``Field``.
    :param advanced: Whether to flag the field as ``advanced``.
    :param kwargs: Additional keyword arguments forwarded to ``Field``.
    :return: A Pydantic field marked NOT_OVERRIDABLE.
    """
    metadata = {
        FieldMarkerKey.RELOAD: ReloadClassification.NOT_OVERRIDABLE,
        **({FieldMarkerKey.ADVANCED: True} if advanced else {}),
    }
    return field_with_metadata(default, metadata=metadata, **kwargs)


def is_nested_overridable_parent(
    settings_cls: type[BaseModel],
    field_name: str,
    *,
    include_policy_gate: bool = True,
) -> bool:
    """Return whether ``field_name`` accepts nested-child overrides.

    ``True`` iff the field's classification is :attr:`ReloadClassification.HOT`
    OR :attr:`ReloadClassification.NESTED_ONLY`. ``False`` for unknown fields
    and for fields classified ``NOT_OVERRIDABLE``.

    Under an active allowlist the parent additionally has to lead somewhere: one
    allowed descendant keeps it addressable, while a parent whose every leaf is
    withheld stops accepting nested overrides entirely.

    Used by :func:`app.core.settings_override.api.routes._validate_patch_body`
    and :func:`app.core.settings_override.cache.build_snapshot` to gate
    ``__``-delimited keys at the parent level before walking into the nested
    resolver.

    :param settings_cls: The Pydantic settings class declaring the field.
    :param field_name: The top-level field name.
    :param include_policy_gate: Whether to also require
        ``SETTINGS_OVERRIDE.ALLOWED_KEYS`` to leave something reachable under the
        parent. Pass ``False`` to ask only whether the key is addressable at all,
        which is what keeps a stale row under a fully withheld parent deletable.
    :return: ``True`` iff nested-child overrides may target this field.
    """
    info = settings_cls.model_fields.get(field_name)
    if info is None:
        return False
    markers = _effective_field_markers(
        info, owner_cls=settings_cls, field_name=field_name
    )
    if markers.get(FieldMarkerKey.RELOAD) not in {
        ReloadClassification.HOT,
        ReloadClassification.NESTED_ONLY,
    }:
        return False
    if not include_policy_gate or not is_restriction_active():
        return True
    setting_class = _setting_class_or_none(settings_cls)
    if setting_class is None:
        return False
    return has_allowed_key_under(setting_class, field_name)


def nested_overridable_field_names(
    settings_cls: type[BaseModel],
) -> frozenset[str]:
    """Return the set of field names on ``settings_cls`` marked ``NESTED_ONLY``.

    Parallels :func:`hot_field_names`. Used by tests and by future tooling that
    needs to surface which parents accept nested overrides.

    :param settings_cls: The Pydantic settings class to introspect.
    :type settings_cls: type[BaseModel]
    :return: A frozenset of field names declared NESTED_ONLY.
    :rtype: frozenset[str]
    """
    return frozenset(
        name
        for name, info in settings_cls.model_fields.items()
        if _effective_field_markers(info, owner_cls=settings_cls, field_name=name).get(
            FieldMarkerKey.RELOAD
        )
        == ReloadClassification.NESTED_ONLY
    )


def _resolve_field_in_model(
    model_cls: type[BaseModel], segment: str
) -> tuple[str, FieldInfo] | None:
    """Return ``(canonical_attribute_name, FieldInfo)`` for ``segment`` on ``model_cls``.

    Performs case-insensitive matching across:

    1. The Pydantic attribute name in ``model_cls.model_fields``.
    2. The field's ``alias`` / ``validation_alias`` / ``serialization_alias``.

    Required so that ``SECURITY_HEADERS__X_FRAME_OPTIONS_DENY`` (uppercase, the
    override-key convention) resolves to ``x_frame_options_deny`` on
    :class:`app.core.middleware.security_headers.SecurityHeadersOptions` (a
    ``BaseCaseInsensitiveModel`` declaring lowercase attribute names with an
    uppercase alias).

    :param model_cls: The Pydantic model class to search.
    :type model_cls: type[BaseModel]
    :param segment: The path segment to resolve.
    :type segment: str
    :return: ``(attribute_name, FieldInfo)`` on success, or ``None`` when no
        field matches.
    :rtype: tuple[str, FieldInfo] | None
    """
    if segment in model_cls.model_fields:
        return segment, model_cls.model_fields[segment]
    seg_lower = segment.lower()
    for name, info in model_cls.model_fields.items():
        if name.lower() == seg_lower:
            return name, info
        for alias in (info.alias, info.validation_alias, info.serialization_alias):
            if isinstance(alias, str) and alias.lower() == seg_lower:
                return name, info
    return None


def _resolve_nested_segments(
    settings_cls: type[BaseModel],
    key: str,
) -> list[tuple[type[BaseModel], str, FieldInfo]] | None:
    """Resolve every ``__`` segment of ``key`` to ``(owner_cls, canonical_name, FieldInfo)``.

    Walks one segment at a time, descending into nested Pydantic models. Returns
    ``None`` when any segment is unresolvable, the path hits a non-Pydantic
    intermediate, or the key is empty. The list preserves order from the
    top-level parent down to the leaf, so callers can inspect intermediate
    fields (e.g. for an explicit ``not_overridable_field`` marker) and not just
    the leaf. Each entry carries its owning class so classifiers can consult that
    class's :data:`INHERITED_MARKERS_ATTR` overlay.

    :param settings_cls: The top-level Pydantic settings class.
    :type settings_cls: type[BaseModel]
    :param key: The ``__``-delimited override key.
    :type key: str
    :return: One ``(owner_cls, canonical_name, FieldInfo)`` per segment, or ``None``.
    :rtype: list[tuple[type[BaseModel], str, FieldInfo]] | None
    """
    if not key:
        return None
    segments = key.split("__")
    resolved_chain = []
    current_cls = settings_cls
    for i, seg in enumerate(segments):
        resolved = _resolve_field_in_model(current_cls, seg)
        if resolved is None:
            return None
        canonical, info = resolved
        resolved_chain.append((current_cls, canonical, info))
        if i < len(segments) - 1:
            next_cls = annotation_pydantic_class(info.annotation)
            if next_cls is None:
                return None
            current_cls = next_cls
    return resolved_chain


def resolve_nested_field(
    settings_cls: type[BaseModel],
    key: str,
) -> tuple[tuple[str, ...], FieldInfo] | None:
    """Resolve a ``__``-delimited path to its canonical attribute chain and leaf field.

    Walks one segment at a time, descending into nested Pydantic models.
    Returns ``None`` when any segment is unresolvable, the path hits a
    non-Pydantic intermediate, or the path is empty.

    The returned chain uses canonical (case-corrected) attribute names so the
    caller can plug it straight into nested ``model_copy(update=...)`` calls.

    :param settings_cls: The top-level Pydantic settings class.
    :type settings_cls: type[BaseModel]
    :param key: The override key to resolve (e.g.
        ``"SECURITY_HEADERS__STRICT_TRANSPORT_SECURITY__MAX_AGE"``).
    :type key: str
    :return: ``((canonical_segment, ...), leaf_FieldInfo)`` or ``None``.
    :rtype: tuple[tuple[str, ...], FieldInfo] | None
    """
    resolved = _resolve_nested_segments(settings_cls, key)
    if resolved is None:
        return None
    return tuple(name for _owner, name, _info in resolved), resolved[-1][2]


def chain_has_explicit_not_overridable(settings_cls: type[BaseModel], key: str) -> bool:
    """Return whether any segment of a nested key is explicitly not-overridable.

    Unlike checking only the resolved leaf, this walks every segment from the
    top-level parent to the leaf and reports ``True`` if *any* of them carries an
    explicit :func:`not_overridable_field` marker. An intermediate model marked
    not-overridable therefore blocks overrides of its descendants, matching the
    contract a reader would expect from the marker. Returns ``False`` for an
    unresolvable key (the caller surfaces the resolution failure separately).

    :param settings_cls: The top-level Pydantic settings class.
    :type settings_cls: type[BaseModel]
    :param key: The ``__``-delimited override key.
    :type key: str
    :return: ``True`` iff some segment is explicitly ``NOT_OVERRIDABLE``.
    :rtype: bool
    """
    resolved = _resolve_nested_segments(settings_cls, key)
    if resolved is None:
        return False
    return any(
        is_explicit_not_overridable(info, owner_cls=owner, field_name=name)
        for owner, name, info in resolved
    )


def chain_has_advanced(settings_cls: type[BaseModel], key: str) -> bool:
    """Return whether any segment of a nested key is flagged ``advanced``.

    Walks every segment from the top-level parent down to the leaf -- mirroring
    :func:`chain_has_explicit_not_overridable` -- and reports ``True`` if *any* of
    them carries an ``advanced`` marker. A parent marked advanced therefore
    propagates the flag to every leaf it expands into, which is
    the only way the dashboard sees ``advanced`` for the session and
    security-header fields whose parent, not leaves, is marked. Returns ``False``
    for an unresolvable key.

    :param settings_cls: The top-level Pydantic settings class.
    :param key: The ``__``-delimited override key.
    :return: ``True`` iff some segment in the chain is flagged ``advanced``.
    """
    resolved = _resolve_nested_segments(settings_cls, key)
    if resolved is None:
        return False
    return any(
        is_advanced_field(info, owner_cls=owner, field_name=name)
        for owner, name, info in resolved
    )


def chain_is_locked(settings_cls: type[BaseModel], key: str) -> bool:
    """Return whether a nested key is closed to overrides, statically or by policy.

    Composes the two independent reasons a nested path may be refused: an
    explicit :func:`not_overridable_field` marker anywhere along the chain
    (:func:`chain_has_explicit_not_overridable`), or
    ``SETTINGS_OVERRIDE.ALLOWED_KEYS`` withholding the leaf. The policy lookup
    uses the canonical chain rather than ``key`` as spelled, so a
    case-insensitive spelling reaches the same verdict as the row it would
    resolve to. Returns ``False`` for an unresolvable key (the caller surfaces
    the resolution failure separately).

    Kept distinct from :func:`chain_has_explicit_not_overridable`, which stays
    purely static: telling "locked by the code" from "locked by the allowlist"
    is what lets DELETE clear a stale row for a key the allowlist withheld.

    :param settings_cls: The top-level Pydantic settings class.
    :param key: The ``__``-delimited override key.
    :return: ``True`` iff an override of ``key`` would be refused.
    """
    resolved = _resolve_nested_segments(settings_cls, key)
    if resolved is None:
        return False
    if any(
        is_explicit_not_overridable(info, owner_cls=owner, field_name=name)
        for owner, name, info in resolved
    ):
        return True
    canonical_key = "__".join(name for _owner, name, _info in resolved)
    return _policy_locked(settings_cls, canonical_key)


def coerce_nested_field_value(
    settings_cls: type[BaseModel],
    key: str,
    raw: Any,
) -> tuple[tuple[str, ...], Any]:
    """Resolve ``key`` to a nested attribute chain and coerce ``raw`` to the leaf type.

    Combines :func:`resolve_nested_field` and :func:`coerce_field_value` so the
    cache and API layers have one entry point for the full nested-row coercion
    contract. A path whose leaf *or any intermediate* is explicitly classified
    ``NOT_OVERRIDABLE``, or whose leaf ``SETTINGS_OVERRIDE.ALLOWED_KEYS``
    withholds, is rejected by raising :class:`KeyError`, matching the
    unresolvable-path contract so the caller's existing ``except KeyError``
    branch logs and skips uniformly.

    :param settings_cls: The top-level Pydantic settings class.
    :param key: The override row's ``__``-delimited key.
    :param raw: The raw JSON-decoded value to coerce.
    :return: ``((canonical_segment, ...), coerced_value)``.
    :raises KeyError: If the path is unresolvable on ``settings_cls``, any
        segment along it is explicitly classified ``NOT_OVERRIDABLE``, or
        ``SETTINGS_OVERRIDE.ALLOWED_KEYS`` does not allow overriding the leaf.
    :raises ValidationError: If ``raw`` cannot be coerced to the leaf's type.
    """
    resolved = _resolve_nested_segments(settings_cls, key)
    if resolved is None:
        raise KeyError(key)
    if chain_is_locked(settings_cls, key):
        raise KeyError(key)
    chain = tuple(name for _owner, name, _info in resolved)
    leaf_info = resolved[-1][2]
    return chain, coerce_field_value(leaf_info, raw)


def _mapping_segment_or_default(
    mapping: Mapping[str, Any], segment: str, default: Any
) -> Any:
    """Read ``segment`` from ``mapping`` (case-insensitive) or return ``default``."""
    if segment in mapping:
        return mapping[segment]
    seg_lower = segment.lower()
    for key, value in mapping.items():
        if isinstance(key, str) and key.lower() == seg_lower:
            return value
    return default


def resolve_nested_value(
    *,
    settings_cls: type[BaseModel],
    proxy: OverridableSettingsProxy,
    key: str,
) -> tuple[FieldInfo, Any]:
    """Return the leaf field metadata and current value for a nested key.

    Walks the chain segment by segment using the resolver's canonical
    (case-corrected) names, so the returned value reflects the merged snapshot
    copy when an override is active and the YAML/env value otherwise. Each
    segment is read as a :class:`~collections.abc.Mapping` key when the current
    node is a mapping, and as an attribute otherwise. A **missing** segment
    returns :data:`NESTED_VALUE_MISSING`; a present ``None`` intermediate
    collapses the leaf to ``None`` (optional-intermediate contract).

    :param settings_cls: The Pydantic settings class the key belongs to.
    :type settings_cls: type[BaseModel]
    :param proxy: The proxy whose attribute chain yields the current value.
    :type proxy: OverridableSettingsProxy
    :param key: The ``__``-delimited nested key.
    :type key: str
    :return: A ``(leaf_FieldInfo, current_value)`` pair. ``current_value`` may
        be :data:`NESTED_VALUE_MISSING` when a segment is absent.
    :rtype: tuple[FieldInfo, Any]
    :raises KeyError: If ``key`` does not resolve to a nested field on
        ``settings_cls``.
    """
    resolved = resolve_nested_field(settings_cls, key)
    if resolved is None:
        raise KeyError(key)
    chain, leaf_info = resolved
    current = proxy
    for segment in chain:
        if current is None:
            return leaf_info, None
        if isinstance(current, Mapping):
            segment_value = _mapping_segment_or_default(
                current, segment, NESTED_VALUE_MISSING
            )
            if segment_value is NESTED_VALUE_MISSING:
                return leaf_info, NESTED_VALUE_MISSING
            current = segment_value
            continue
        if not hasattr(current, segment):
            return leaf_info, NESTED_VALUE_MISSING
        current = getattr(current, segment)
    return leaf_info, current


def canonical_override_key(settings_cls: type[BaseModel], key: str) -> str:
    """Return the canonical ``__``-joined attribute path for a nested key.

    Case-insensitive spellings of the same nested path (e.g.
    ``security_headers__x_frame_options_deny`` and its uppercase form) collapse
    to one deterministic key so DB rows, snapshot lookups, and DELETE/GET by key
    all agree. Top-level keys and keys that do not resolve are returned
    unchanged.

    :param settings_cls: The Pydantic settings class the key belongs to.
    :type settings_cls: type[BaseModel]
    :param key: The override key, possibly ``__``-delimited.
    :type key: str
    :return: The canonical key, or ``key`` unchanged when not a resolvable
        nested path.
    :rtype: str
    """
    if "__" not in key:
        return key
    resolved = resolve_nested_field(settings_cls, key)
    if resolved is None:
        return key
    chain, _ = resolved
    return "__".join(chain)


def override_keys_for_rows(
    settings_cls: type[BaseModel],
    rows: list[SettingOverride],
) -> set[str]:
    """Return the set of keys (and canonical prefixes) with active overrides.

    Each row's own ``key`` is included; additionally, every ``__``-delimited row
    contributes every canonical prefix of its resolved chain -- the top-level
    parent, each intermediate sub-model path, and the canonical leaf key. This
    lets a ``field_meta.key in override_keys`` lookup report ``has_override=True``
    for a promoted parent or an intermediate sub-model when only deeper nested
    rows exist, and keeps the flag correct when a row was stored under a
    non-canonical casing.

    :param settings_cls: The Pydantic settings class the rows belong to.
    :type settings_cls: type[BaseModel]
    :param rows: The active override rows for the class.
    :type rows: list[SettingOverride]
    :return: The set of keys and canonical prefixes carrying an override.
    :rtype: set[str]
    """
    keys = {row.key for row in rows}
    for row in rows:
        if "__" not in row.key:
            continue
        resolved = resolve_nested_field(settings_cls, row.key)
        if resolved is None:
            continue
        chain, _ = resolved
        for i in range(1, len(chain) + 1):
            keys.add("__".join(chain[:i]))
    return keys


def _clear_cached_properties(instance: BaseModel) -> None:
    """Remove every ``@cached_property`` memo from ``instance.__dict__``.

    Pydantic ``model_copy()`` is shallow and carries over any
    :class:`functools.cached_property` values that were already evaluated on
    the source instance. Drop them so the copy recomputes lazily against its
    new (possibly overridden) field values.

    :param instance: The freshly-copied Pydantic instance to clean.
    :type instance: BaseModel
    """
    cls = type(instance)
    for name in list(instance.__dict__):
        # ``getattr`` walks the full MRO, so a ``cached_property`` declared on a
        # base class (e.g. ``BaseRemoteAPI.logger``) is cleared too -- scanning
        # only ``cls.__dict__`` would leave those inherited memos stale.
        if isinstance(getattr(cls, name, None), functools.cached_property):
            del instance.__dict__[name]


@dataclass(slots=True, frozen=True, kw_only=True)
class FieldMetadata:
    """Represent introspected metadata for a single settings field.

    :param key: The field name on the owning settings class.
    :type key: str
    :param annotation: The field's declared Python annotation (without any
        constraint metadata reassembly).
    :type annotation: Any
    :param default: The field's declared default value, or
        :data:`pydantic_core.PydanticUndefined` when no default exists.
    :type default: Any
    :param description: The field's free-text description, or ``None`` when
        not declared.
    :type description: str | None
    :param reload: The reload classification for this field
        (``HOT`` or ``NOT_OVERRIDABLE``).
    :type reload: ReloadClassification
    :param is_secret: Whether the field's annotation contains a
        :class:`pydantic.SecretStr` / :class:`pydantic.SecretBytes`, either at
        the top level or nested inside a Pydantic submodel.
    :type is_secret: bool
    :param is_complex: Whether the field's annotation is or contains a Pydantic
        :class:`pydantic.BaseModel` subclass (true for nested submodels and
        unions containing them).
    :type is_complex: bool
    :param is_advanced: Whether the field is flagged ``advanced`` for UI grouping.
        For a nested leaf this is chain-resolved: ``True`` when the leaf or any
        ancestor is marked. Display-only; does not affect override eligibility.
    """

    key: str
    annotation: Any
    default: Any
    description: str | None
    reload: ReloadClassification
    is_secret: bool
    is_complex: bool
    is_advanced: bool = False


def _iter_type_arguments(annotation: Any) -> Iterator[Any]:
    """Yield every type argument referenced by ``annotation`` recursively.

    Walks unions, generic containers (``list[X]``, ``dict[K, V]``, etc.) and
    :class:`pydantic.BaseModel` subclasses, descending into the latter's
    fields so nested model attributes are inspected too. Also queues each
    model's ``__subclasses__()`` so secrets declared only on concrete
    subclasses of a polymorphic base remain reachable (limited to subclasses
    already imported when this runs).

    :param annotation: The type annotation to walk.
    :return: An iterator over the referenced type arguments.
    """
    seen = set()
    stack = [annotation]
    while stack:
        current = stack.pop()
        if current is None or current is type(None):
            continue
        ident = id(current)
        if ident in seen:
            continue
        seen.add(ident)
        yield current
        origin = typing.get_origin(current)
        if origin in {Union, UnionType} or origin is not None:
            stack.extend(typing.get_args(current))
            continue
        if isinstance(current, type) and issubclass(current, BaseModel):
            stack.extend(nested.annotation for nested in current.model_fields.values())
            stack.extend(current.__subclasses__())


#: Pydantic's default JSON dump mask for :class:`~pydantic.SecretStr` /
#: :class:`~pydantic.SecretBytes`. Distinct from
#: :data:`~app.core.utils.fields.CREDENTIAL_URL_MASK` (``"****"``).
SECRET_STR_MASK = "**********"  # noqa: S105 # nosec B105


def _field_contains_secret(field_info: FieldInfo) -> bool:
    """Return whether ``field_info`` exposes a Pydantic secret anywhere in its annotation.

    Walks the annotation recursively via :func:`_iter_type_arguments`
    (nested models and imported concrete subclasses of polymorphic bases),
    looking for :class:`pydantic.SecretStr` or :class:`pydantic.SecretBytes`.

    :param field_info: The Pydantic field metadata for the target attribute.
    :return: ``True`` when a secret type is reachable from the annotation.
    """
    secret_types = (SecretStr, SecretBytes)
    for arg in _iter_type_arguments(field_info.annotation):
        if isinstance(arg, type) and issubclass(arg, secret_types):
            return True
    return False


def _unwrap_secret_value(current: Any) -> str | bytes | None:
    """Return the plain secret from a ``SecretStr``/``SecretBytes``, else ``None``.

    :param current: A live stored value that may be a Pydantic secret wrapper.
    :return: ``get_secret_value()`` when ``current`` is a secret instance;
        ``None`` otherwise.
    """
    if isinstance(current, SecretStr | SecretBytes):
        return current.get_secret_value()
    return None


def unwrap_secrets_for_storage(value: Any) -> Any:
    """Return a JSON-column-safe form of ``value`` with secrets as plaintext.

    Override rows persist through a JSON column. Assigning a
    :class:`~pydantic.SecretStr` / :class:`~pydantic.SecretBytes` (or a
    model/mapping that contains one) is unsafe: Pydantic's secret-aware
    serialisation rewrites the credential to :data:`SECRET_STR_MASK`, and that
    mask is what ends up stored. Snapshot load expects plaintext JSON and
    re-wraps via :func:`coerce_field_value` / :func:`materialize_override_value`.

    :param value: A coerced/materialized PATCH value, possibly containing
        secret wrappers.
    :return: ``value`` with every secret wrapper replaced by its plain
        ``get_secret_value()`` (``SecretBytes`` decoded as UTF-8 with
        surrogateescape so the result stays JSON-serialisable).
    """
    unwrapped = _unwrap_secret_value(value)
    if unwrapped is not None:
        if isinstance(unwrapped, bytes):
            return unwrapped.decode("utf-8", errors="surrogateescape")
        return unwrapped
    if isinstance(value, BaseModel):
        return {
            name: unwrap_secrets_for_storage(getattr(value, name))
            for name in value.__class__.model_fields
        }
    if isinstance(value, Mapping):
        return {key: unwrap_secrets_for_storage(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [unwrap_secrets_for_storage(item) for item in value]
    return value


def _metadata_has_credential_url_serializer(metadata: tuple[Any, ...]) -> bool:
    """Return whether ``metadata`` carries the credential URL JSON serializer."""
    return any(
        isinstance(item, WrapSerializer) and item.func is _credential_url_serializer
        for item in metadata
    )


def is_credential_url_field(field_info: FieldInfo) -> bool:
    """Return whether ``field_info`` serializes as a credential-bearing URL."""
    if _metadata_has_credential_url_serializer(field_info.metadata):
        return True
    for arg in _iter_type_arguments(field_info.annotation):
        if _metadata_has_credential_url_serializer(getattr(arg, "__metadata__", ())):
            return True
    return False


def _read_mapping_or_model_attr(current: Any, name: str) -> Any:
    """Read ``name`` from a live model or a materializer fingerprint mapping."""
    if current is None:
        return None
    if isinstance(current, Mapping):
        return current.get(name)
    return getattr(current, name, None)


def preserve_credential_urls_in_model_payload(
    model_cls: type[BaseModel],
    current: Any,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Restore masked URL passwords inside a materializer PATCH payload."""
    result = dict(incoming)
    for name, field_info in model_cls.model_fields.items():
        if name not in result:
            continue
        leaf_current = _read_mapping_or_model_attr(current, name)
        if is_credential_url_field(field_info):
            if isinstance(result[name], str) and leaf_current is not None:
                result[name] = preserve_credential_url_password(
                    str(leaf_current), result[name]
                )
            continue
        nested_cls = annotation_pydantic_class(field_info.annotation)
        if nested_cls and isinstance(result[name], Mapping):
            result[name] = preserve_credential_urls_in_model_payload(
                nested_cls, leaf_current, result[name]
            )
    return result


def preserve_patch_credential_url_value(
    field_info: FieldInfo,
    current: Any,
    incoming: Any,
) -> Any:
    """Restore masked credentials in a PATCH value before validation/persist.

    Handles credential-bearing URL passwords (``****``) and
    :class:`~pydantic.SecretStr` / :class:`~pydantic.SecretBytes` JSON masks
    (:data:`SECRET_STR_MASK`). Non-mask submissions are left unchanged.

    Routing is decided by the payload shape before
    :func:`is_credential_url_field` is consulted. That predicate descends into
    nested models, so it answers "does this subtree carry a credential URL",
    not "is this field itself one" -- and a model-typed field holding a
    credential-URL leaf answers ``True`` to the first question while needing
    the model-payload walk, not the scalar restore.

    :param field_info: The Pydantic field metadata for the target attribute.
    :param current: The effective stored value (model, mapping, or secret wrapper).
    :param incoming: The value submitted in the PATCH body.
    :return: ``incoming`` with any masked credentials restored from ``current``.
    """
    parent_cls = annotation_pydantic_class(field_info.annotation)
    if parent_cls is not None and isinstance(incoming, Mapping):
        value = preserve_credential_urls_in_model_payload(parent_cls, current, incoming)
    elif (
        is_credential_url_field(field_info)
        and isinstance(incoming, str)
        and current is not None
    ):
        value = preserve_credential_url_password(str(current), incoming)
    else:
        value = incoming
    return preserve_patch_secret_value(field_info, current, value)


def _annotation_is_secret_valued_dict(annotation: Any) -> bool:
    """Return whether ``annotation`` is a ``dict`` whose values are secrets.

    Unwraps optional/union wrappers at the top level only (does not descend into
    nested :class:`~pydantic.BaseModel` fields), matching
    ``dict[str, SecretStr]`` / ``dict[str, SecretBytes]`` shapes.

    :param annotation: The field annotation to inspect.
    :return: ``True`` when the annotation is a secret-valued mapping type.
    """
    candidates: list[Any] = [annotation]
    origin = typing.get_origin(annotation)
    if origin in {Union, UnionType}:
        candidates = list(typing.get_args(annotation))
    for candidate in candidates:
        if candidate is None or candidate is type(None):
            continue
        dict_origin = typing.get_origin(candidate)
        if dict_origin not in {dict, Mapping}:
            continue
        try:
            _, value_ann = typing.get_args(candidate)
        except ValueError:
            continue
        value_candidates: list[Any] = [value_ann]
        value_origin = typing.get_origin(value_ann)
        if value_origin in {Union, UnionType}:
            value_candidates = list(typing.get_args(value_ann))
        for value_type in value_candidates:
            if isinstance(value_type, type) and issubclass(
                value_type, SecretStr | SecretBytes
            ):
                return True
    return False


def _annotation_is_secret_valued_sequence(annotation: Any) -> bool:
    """Return whether ``annotation`` is a collection whose elements are secrets.

    Matches ``list[SecretStr]`` / ``set[SecretStr]`` /
    ``tuple[SecretBytes, ...]``-style shapes (optional/union wrappers
    unwrapped at the top level only).

    :param annotation: The field annotation to inspect.
    :return: ``True`` when the annotation is a secret-element collection type.
    """
    candidates: list[Any] = [annotation]
    origin = typing.get_origin(annotation)
    if origin in {Union, UnionType}:
        candidates = list(typing.get_args(annotation))
    collection_origins = {list, set, tuple, frozenset, Sequence}
    for candidate in candidates:
        if candidate is None or candidate is type(None):
            continue
        coll_origin = typing.get_origin(candidate)
        if coll_origin not in collection_origins:
            continue
        args = typing.get_args(candidate)
        if not args:
            continue
        element = args[0]
        element_candidates: list[Any] = [element]
        element_origin = typing.get_origin(element)
        if element_origin in {Union, UnionType}:
            element_candidates = list(typing.get_args(element))
        for element_type in element_candidates:
            if isinstance(element_type, type) and issubclass(
                element_type, SecretStr | SecretBytes
            ):
                return True
    return False


def _stable_collection_sort_key(item: Any) -> tuple[Any, ...]:
    """Return a deterministic sort key for collection pairing and JSON dumps.

    Unordered collections (``set``/``frozenset``) must serialize and match in
    the same order across workers; plaintext secret values are included so two
    otherwise identical models remain distinguishable before masking.

    :param item: A stored collection element (model, secret wrapper, or scalar).
    :return: A comparable tuple suitable for :func:`sorted`.
    """
    if isinstance(item, BaseModel):
        field_parts: list[tuple[str, str]] = []
        for name in sorted(item.model_fields):
            value = getattr(item, name, None)
            unwrapped = _unwrap_secret_value(value)
            if unwrapped is not None:
                rendered = unwrapped if isinstance(unwrapped, str) else repr(unwrapped)
            else:
                rendered = repr(value)
            field_parts.append((name, rendered))
        return (item.__class__.__qualname__, tuple(field_parts))
    unwrapped = _unwrap_secret_value(item)
    if unwrapped is not None:
        return (
            type(item).__qualname__,
            unwrapped if isinstance(unwrapped, str | bytes) else repr(unwrapped),
        )
    if isinstance(item, Mapping):
        return (
            "mapping",
            tuple(
                (
                    str(key),
                    repr(
                        stored
                        if (stored := _unwrap_secret_value(value)) is not None
                        else value
                    ),
                )
                for key, value in sorted(item.items(), key=lambda kv: str(kv[0]))
            ),
        )
    return (type(item).__qualname__, repr(item))


def _stable_collection_items(current: Any) -> list[Any]:
    """Return ``current`` as a list, sorting when the source is unordered.

    :param current: A stored ``list``/``set``/``tuple``/``frozenset``, or
        ``None``.
    :return: A list of items; ``set``/``frozenset`` inputs are sorted by
        :func:`_stable_collection_sort_key`.
    """
    if isinstance(current, set | frozenset):
        return sorted(current, key=_stable_collection_sort_key)
    if isinstance(current, list | tuple):
        return list(current)
    return []


def _collection_item_value_score(
    incoming: Mapping[str, Any], current: BaseModel
) -> int:
    """Score how well ``incoming`` identifies the stored model ``current``.

    Masked secret fields are ignored so a round-tripped GET payload can still
    match on stable non-secret identity (e.g. ``api_endpoint``). Equal
    non-masked values raise the score; mismatches lower it.

    :param incoming: One element of the PATCH collection payload.
    :param current: A live stored model candidate.
    :return: A higher score means a better identity match.
    """
    score = 0
    for name in current.model_fields:
        if name not in incoming:
            continue
        incoming_val = incoming[name]
        if incoming_val == SECRET_STR_MASK:
            continue
        current_val = getattr(current, name, None)
        unwrapped = _unwrap_secret_value(current_val)
        compare: Any = unwrapped if unwrapped is not None else current_val
        if incoming_val == compare or str(incoming_val) == str(compare):
            score += 2
        else:
            score -= 10
    return score


def _preserve_masked_secret_scalar(current: Any, incoming: Any) -> Any:
    """Restore a stored secret when ``incoming`` equals :data:`SECRET_STR_MASK`.

    :param current: The live stored value, possibly a ``SecretStr``/``SecretBytes``.
    :param incoming: The PATCH value that may be the secret JSON mask.
    :return: The unwrapped stored secret when ``incoming`` is the mask and
        ``current`` is a secret wrapper; otherwise ``incoming`` unchanged.
    """
    if incoming != SECRET_STR_MASK:
        return incoming
    stored = _unwrap_secret_value(current)
    return incoming if stored is None else stored


def _preserve_secrets_in_dict_payload(
    current: Any,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Restore masked secret values inside a ``dict[str, SecretStr|SecretBytes]`` payload.

    :param current: The stored mapping of secret wrappers (or ``None``).
    :param incoming: The PATCH mapping that may contain mask literals.
    :return: A copy of ``incoming`` with masked keys restored from ``current``.
    """
    result = dict(incoming)
    for key, value in result.items():
        if value != SECRET_STR_MASK:
            continue
        leaf_current = current.get(key) if isinstance(current, Mapping) else None
        stored = _unwrap_secret_value(leaf_current)
        if stored is not None:
            result[key] = stored
    return result


def _preserve_secrets_in_secret_sequence_payload(
    current: Any,
    incoming: Sequence[Any],
) -> list[Any]:
    """Restore masked secrets inside a secret-element collection payload.

    Pairing is positional against :func:`_stable_collection_items`: index ``i``
    of ``incoming`` is restored from index ``i`` of the stabilized ``current``
    when the submitted value equals :data:`SECRET_STR_MASK`. Unordered stored
    collections (``set``/``frozenset``) are sorted so GET/PATCH workers agree.

    :param current: The stored collection of secret wrappers (or ``None``).
    :param incoming: The PATCH sequence that may contain mask literals.
    :return: A list copy of ``incoming`` with masked elements restored.
    """
    current_items = _stable_collection_items(current)
    result: list[Any] = []
    for index, value in enumerate(incoming):
        if value != SECRET_STR_MASK:
            result.append(value)
            continue
        leaf = current_items[index] if index < len(current_items) else None
        stored = _unwrap_secret_value(leaf)
        result.append(value if stored is None else stored)
    return result


def _annotation_collection_element_model(annotation: Any) -> type[BaseModel] | None:
    """Return the ``BaseModel`` element type of a ``list``/``set``/``tuple`` annotation.

    Unwraps optional/union wrappers at the top level. Matches shapes such as
    ``set[SomeModel]`` or ``list[SomeModel]``; returns ``None`` for scalars,
    mappings, and collections whose element type is not a Pydantic model.

    :param annotation: The field annotation to inspect.
    :return: The element ``BaseModel`` subclass, or ``None``.
    """
    candidates: list[Any] = [annotation]
    origin = typing.get_origin(annotation)
    if origin in {Union, UnionType}:
        candidates = list(typing.get_args(annotation))
    collection_origins = {list, set, tuple, frozenset, Sequence}
    for candidate in candidates:
        if candidate is None or candidate is type(None):
            continue
        coll_origin = typing.get_origin(candidate)
        if coll_origin not in collection_origins:
            continue
        args = typing.get_args(candidate)
        if not args:
            continue
        element = args[0]
        element_candidates: list[Any] = [element]
        element_origin = typing.get_origin(element)
        if element_origin in {Union, UnionType}:
            element_candidates = list(typing.get_args(element))
        for element_type in element_candidates:
            if isinstance(element_type, type) and issubclass(element_type, BaseModel):
                return element_type
    return None


def _collection_discriminator_candidates(
    incoming: Mapping[str, Any],
    current_items: Sequence[Any],
    used: set[int],
) -> list[int]:
    """Return unused model indexes matching an optional type discriminator.

    :param incoming: One element of the PATCH collection payload.
    :param current_items: The live stored collection as a sequence.
    :param used: Indexes already paired with an earlier incoming element.
    :return: Candidate indexes; empty when none match the discriminator filter.
    """
    provider = incoming.get("PROVIDER") or incoming.get("provider")
    needle = str(provider).upper() if provider is not None else None
    candidates: list[int] = []
    for index, current in enumerate(current_items):
        if index in used or not isinstance(current, BaseModel):
            continue
        if needle is not None and needle not in current.__class__.__name__.upper():
            continue
        candidates.append(index)
    return candidates


def _pick_best_scored_index(
    incoming: Mapping[str, Any],
    current_items: Sequence[Any],
    candidates: Sequence[int],
    preferred_index: int,
) -> int:
    """Pick the candidate with the best value-identity score.

    Ties break on ``preferred_index`` when that slot is among the top scorers.

    :param incoming: One element of the PATCH collection payload.
    :param current_items: The live stored collection as a sequence.
    :param candidates: Unused model indexes to score.
    :param preferred_index: The incoming element's position (list order).
    :return: The winning index into ``current_items``.
    """
    best_score = _collection_item_value_score(incoming, current_items[candidates[0]])
    best_indices = [candidates[0]]
    for index in candidates[1:]:
        score = _collection_item_value_score(incoming, current_items[index])
        if score > best_score:
            best_score = score
            best_indices = [index]
        elif score == best_score:
            best_indices.append(index)
    if preferred_index in best_indices:
        return preferred_index
    return best_indices[0]


def _match_by_field_name_overlap(
    incoming: Mapping[str, Any],
    current_items: Sequence[Any],
    unused: Sequence[int],
) -> int | None:
    """Return the unused model with the largest field-name overlap, if any.

    :param incoming: One element of the PATCH collection payload.
    :param current_items: The live stored collection as a sequence.
    :param unused: Indexes not yet paired.
    :return: The best-overlap index, or ``None``.
    """
    best_index: int | None = None
    best_overlap = 0
    incoming_keys = set(incoming)
    for index in unused:
        current = current_items[index]
        if not isinstance(current, BaseModel):
            continue
        overlap = len(set(current.model_fields) & incoming_keys)
        if overlap > best_overlap:
            best_overlap = overlap
            best_index = index
    return best_index if best_overlap > 0 else None


def _match_collection_item_index(
    incoming: Mapping[str, Any],
    current_items: Sequence[Any],
    used: set[int],
    preferred_index: int,
) -> int | None:
    """Return the index of the stored collection item that ``incoming`` updates.

    Matching order: optional type-discriminator (case-insensitive substring of
    the concrete class name) narrows candidates; among those, non-masked field
    value identity (:func:`_collection_item_value_score`) picks a winner;
    ties break on ``preferred_index`` when that slot is still a candidate
    (stable against :func:`_stable_collection_items` order); else the sole
    remaining unused item; else largest field-name overlap.

    :param incoming: One element of the PATCH collection payload.
    :param current_items: The live stored collection as a sequence.
    :param used: Indexes already paired with an earlier incoming element.
    :param preferred_index: The incoming element's position (list order).
    :return: The matched index into ``current_items``, or ``None``.
    """
    candidates = _collection_discriminator_candidates(incoming, current_items, used)
    if candidates:
        return _pick_best_scored_index(
            incoming, current_items, candidates, preferred_index
        )
    if preferred_index < len(current_items) and preferred_index not in used:
        return preferred_index
    unused = [index for index in range(len(current_items)) if index not in used]
    if len(unused) == 1:
        return unused[0]
    return _match_by_field_name_overlap(incoming, current_items, unused)


def _preserve_secrets_in_sequence_payload(
    current: Any,
    incoming: Sequence[Any],
) -> list[Any]:
    """Restore masked secrets inside a list/set-of-models PATCH payload.

    Pairs each mapping element with a live stored item via
    :func:`_match_collection_item_index` against
    :func:`_stable_collection_items`, then restores masks through
    :func:`preserve_secrets_in_model_payload` using the item's concrete
    runtime class (polymorphic bases often declare no secret fields of their
    own). Fingerprint mappings restore masked keys shallowly.

    :param current: The stored collection (``list``/``set``/``tuple``/
        ``frozenset``) or ``None``.
    :param incoming: The PATCH sequence that may contain mask literals.
    :return: A list copy of ``incoming`` with masked secrets restored.
    """
    current_items = _stable_collection_items(current)
    result: list[Any] = []
    used: set[int] = set()
    for index, item in enumerate(incoming):
        if not isinstance(item, Mapping):
            result.append(item)
            continue
        match_index = _match_collection_item_index(
            item, current_items, used, preferred_index=index
        )
        if match_index is None:
            result.append(dict(item))
            continue
        used.add(match_index)
        matched = current_items[match_index]
        if isinstance(matched, BaseModel):
            result.append(
                preserve_secrets_in_model_payload(type(matched), matched, item)
            )
            continue
        if isinstance(matched, Mapping):
            restored = dict(item)
            for key, value in restored.items():
                if value != SECRET_STR_MASK:
                    continue
                stored = _unwrap_secret_value(matched.get(key))
                if stored is not None:
                    restored[key] = stored
            result.append(restored)
            continue
        result.append(dict(item))
    return result


def preserve_secrets_in_model_payload(
    model_cls: type[BaseModel],
    current: Any,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Restore masked SecretStr/SecretBytes values inside a nested-model PATCH payload.

    Recurses into nested models, secret-valued dicts, secret-element sequences,
    and homogeneous list/set-of-model fields; scalar secret leaves use
    :func:`_preserve_masked_secret_scalar`.

    :param model_cls: The Pydantic model whose fields ``incoming`` addresses.
    :param current: The live stored model or mapping fingerprint.
    :param incoming: The PATCH mapping for this model.
    :return: A copy of ``incoming`` with masked secrets restored from ``current``.
    """
    result = dict(incoming)
    for name, field_info in model_cls.model_fields.items():
        if name not in result:
            continue
        leaf_current = _read_mapping_or_model_attr(current, name)
        nested_cls = annotation_pydantic_class(field_info.annotation)
        if nested_cls and isinstance(result[name], Mapping):
            result[name] = preserve_secrets_in_model_payload(
                nested_cls, leaf_current, result[name]
            )
            continue
        if _annotation_is_secret_valued_dict(field_info.annotation) and isinstance(
            result[name], Mapping
        ):
            result[name] = _preserve_secrets_in_dict_payload(leaf_current, result[name])
            continue
        if _annotation_is_secret_valued_sequence(field_info.annotation) and isinstance(
            result[name], list | tuple
        ):
            result[name] = _preserve_secrets_in_secret_sequence_payload(
                leaf_current, result[name]
            )
            continue
        if _annotation_collection_element_model(field_info.annotation) is not None and (
            isinstance(result[name], list | tuple)
        ):
            result[name] = _preserve_secrets_in_sequence_payload(
                leaf_current, result[name]
            )
            continue
        if _field_contains_secret(field_info):
            result[name] = _preserve_masked_secret_scalar(leaf_current, result[name])
    return result


def preserve_patch_secret_value(
    field_info: FieldInfo,
    current: Any,
    incoming: Any,
) -> Any:
    """Restore masked SecretStr/SecretBytes values in a PATCH value before persist.

    When a client resubmits Pydantic's secret JSON mask
    (:data:`SECRET_STR_MASK`), replace it with the stored secret's plain value.
    Non-mask submissions are left unchanged. Recurses into nested Pydantic
    models, ``dict[str, SecretStr]`` / ``dict[str, SecretBytes]`` payloads,
    ``list[SecretStr]`` / ``set[SecretStr]``-style collections, and homogeneous
    ``list``/``set`` collections of models (including polymorphic bases whose
    secrets live only on concrete subclasses).

    :param field_info: The Pydantic field metadata for the target attribute.
    :param current: The effective stored value (model, mapping, or secret wrapper).
    :param incoming: The value submitted in the PATCH body.
    :return: ``incoming`` with any masked secrets restored from ``current``.
    """
    parent_cls = annotation_pydantic_class(field_info.annotation)
    if parent_cls and isinstance(incoming, Mapping):
        return preserve_secrets_in_model_payload(parent_cls, current, incoming)
    if _annotation_is_secret_valued_dict(field_info.annotation) and isinstance(
        incoming, Mapping
    ):
        return _preserve_secrets_in_dict_payload(current, incoming)
    if isinstance(incoming, list | tuple) and _annotation_is_secret_valued_sequence(
        field_info.annotation
    ):
        return _preserve_secrets_in_secret_sequence_payload(current, incoming)
    if isinstance(incoming, list | tuple) and (
        _annotation_collection_element_model(field_info.annotation) is not None
        or (
            isinstance(current, list | set | tuple | frozenset)
            and any(isinstance(item, BaseModel | Mapping) for item in current)
        )
    ):
        return _preserve_secrets_in_sequence_payload(current, incoming)
    if _field_contains_secret(field_info):
        return _preserve_masked_secret_scalar(current, incoming)
    return incoming


def _field_is_complex(annotation: Any) -> bool:
    """Return whether ``annotation`` is or contains a Pydantic ``BaseModel`` subclass.

    :param annotation: The annotation to inspect.
    :type annotation: Any
    :return: ``True`` when a ``BaseModel`` subclass is reachable from the
        annotation (top-level or inside a union / generic container).
    :rtype: bool
    """
    for arg in _iter_type_arguments(annotation):
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return True
    return False


def iter_class_fields(
    settings_cls: type[BaseYamlSettings],
) -> Iterator[FieldMetadata]:
    """Yield introspected metadata for every field on a settings class.

    Each entry exposes the public attributes the settings API needs without
    leaking :class:`FieldInfo` into the response layer: ``key``, ``annotation``,
    ``default``, ``description``, ``reload`` (HOT or NOT_OVERRIDABLE),
    ``is_secret`` (whether the field's type contains a SecretStr anywhere),
    ``is_complex`` (whether the type is a nested Pydantic model) and
    ``is_advanced`` (whether the field, or an advanced ancestor, is marked
    display-only advanced).

    :param settings_cls: The Pydantic settings class to introspect.
    :type settings_cls: type[BaseYamlSettings]
    :return: An iterator yielding one :class:`FieldMetadata` per declared field.
    :rtype: Iterator[FieldMetadata]
    """
    for name, field in settings_cls.model_fields.items():
        yield FieldMetadata(
            key=name,
            annotation=field.annotation,
            default=_resolve_default(field),
            description=field.description,
            reload=field_reload_classification(
                field, owner_cls=settings_cls, field_name=name
            ),
            is_secret=_field_contains_secret(field),
            is_complex=_field_is_complex(field.annotation),
            is_advanced=is_advanced_field(
                field, owner_cls=settings_cls, field_name=name
            ),
        )


def resolve_nested_field_metadata(
    settings_cls: type[BaseModel], key: str
) -> FieldMetadata | None:
    """Return introspected metadata for a ``__``-delimited nested override key.

    Resolves ``key`` to its leaf field and synthesises a :class:`FieldMetadata`
    whose ``key`` is the full nested key while every other attribute
    (annotation, default, description, secret/complex flags) is taken from the
    leaf field. The reported ``reload`` is ``HOT`` for an override-eligible
    leaf (the default under a nested-overridable parent) and
    ``NOT_OVERRIDABLE`` when the leaf *or any intermediate in its chain* is
    explicitly :func:`not_overridable_field`-marked, or when
    ``SETTINGS_OVERRIDE.ALLOWED_KEYS`` withholds the leaf. That is the same chain
    check that gates PATCH, so the reported classification matches what an
    override would actually be allowed to do. ``is_advanced`` is chain-resolved
    via
    :func:`chain_has_advanced`, so a leaf inherits the flag from an advanced
    parent.

    :param settings_cls: The top-level Pydantic settings class.
    :param key: The ``__``-delimited override key.
    :return: The synthesised leaf metadata, or ``None`` when ``key`` does not
        resolve to a nested field.
    """
    resolved = resolve_nested_field(settings_cls, key)
    if resolved is None:
        return None
    _chain, leaf_info = resolved
    reload = (
        ReloadClassification.NOT_OVERRIDABLE
        if chain_is_locked(settings_cls, key)
        else ReloadClassification.HOT
    )
    return FieldMetadata(
        key=key,
        annotation=leaf_info.annotation,
        default=_resolve_default(leaf_info),
        description=leaf_info.description,
        reload=reload,
        is_secret=_field_contains_secret(leaf_info),
        is_complex=_field_is_complex(leaf_info.annotation),
        is_advanced=chain_has_advanced(settings_cls, key),
    )


def iter_nested_leaf_keys(
    settings_cls: type[BaseModel], parent_field_name: str
) -> Iterator[tuple[str, tuple[str, ...]]]:
    """Yield ``(canonical_key, segment_chain)`` for each nested leaf under a parent.

    Walk the parent submodel's ``model_fields`` recursively, descending into
    Pydantic submodels via :func:`annotation_pydantic_class` (which unwraps
    ``X | None``). A field whose annotation is not a Pydantic model -- a scalar,
    ``list[...]`` or ``set[...]`` -- is a leaf, so collection-typed fields stay a
    single leaf (their items are not expanded). Segments are the canonical
    attribute names from ``model_fields``, so each yielded key matches the form
    :func:`resolve_nested_field` and :func:`override_keys_for_rows` produce, and
    ``"__".join(chain) == key`` holds by construction.

    Yield nothing when ``parent_field_name`` is unknown or is not a Pydantic
    submodel (e.g. a scalar HOT field), letting the caller fall back to a single
    top-level entry.

    :param settings_cls: The settings class declaring ``parent_field_name``.
    :type settings_cls: type[BaseModel]
    :param parent_field_name: The top-level field whose leaves to enumerate.
    :type parent_field_name: str
    :yield: A ``(canonical_key, segment_chain)`` pair for one nested leaf.
    :rtype: Iterator[tuple[str, tuple[str, ...]]]
    """
    parent_info = settings_cls.model_fields.get(parent_field_name)
    if parent_info is None:
        return
    submodel = annotation_pydantic_class(parent_info.annotation)
    if submodel is None:
        return
    yield from _iter_leaf_chains(submodel, (parent_field_name,))


def rendered_leaf_keys(
    settings_cls: type[BaseModel], parent_field_name: str
) -> list[tuple[str, tuple[str, ...]]]:
    """Return the nested leaves the settings listing renders under a parent.

    Empty when the field renders as one whole-object row instead: either it
    accepts no nested overrides at all, or it enumerates no leaves to begin with
    (a scalar HOT field), or every leaf it enumerates carries an explicit
    :func:`not_overridable_field` marker. That last case makes the whole object
    the field's only write unit, so expanding it would advertise leaves no PATCH
    can target while hiding the key that one can. Leaves withheld by
    ``SETTINGS_OVERRIDE.ALLOWED_KEYS`` are not that case; they stay
    enumerated, so an admin can see what the allowlist is holding back.

    :param settings_cls: The settings class declaring ``parent_field_name``.
    :param parent_field_name: The top-level field whose leaves to render.
    :return: The leaves to render, empty to render the parent as one row.
    """
    if not is_nested_overridable_parent(
        settings_cls, parent_field_name, include_policy_gate=False
    ):
        return []
    leaves = list(iter_nested_leaf_keys(settings_cls, parent_field_name))
    if all(
        chain_has_explicit_not_overridable(settings_cls, leaf_key)
        for leaf_key, _chain in leaves
    ):
        return []
    return leaves


def _iter_leaf_chains(
    model_cls: type[BaseModel], prefix: tuple[str, ...]
) -> Iterator[tuple[str, tuple[str, ...]]]:
    """Yield ``(key, chain)`` for every leaf reachable from ``model_cls``, recursing into submodels.

    :param model_cls: The Pydantic model whose fields to walk.
    :type model_cls: type[BaseModel]
    :param prefix: The canonical segment chain accumulated from the parent down
        to (but excluding) ``model_cls``'s own fields.
    :type prefix: tuple[str, ...]
    :yield: A ``(key, chain)`` pair for one leaf reachable from ``model_cls``.
    :rtype: Iterator[tuple[str, tuple[str, ...]]]
    """
    for name, info in model_cls.model_fields.items():
        chain = (*prefix, name)
        child = annotation_pydantic_class(info.annotation)
        if child is None:
            yield "__".join(chain), chain
        else:
            yield from _iter_leaf_chains(child, chain)


def _resolve_default(field_info: FieldInfo) -> Any:
    """Return the field's declared default, invoking ``default_factory`` if any.

    Pydantic sets ``field_info.default`` to :data:`PydanticUndefined` when a
    field is declared with ``Field(default_factory=...)``. Returning that
    sentinel through the metadata layer makes ``dump_field_value`` emit
    ``None`` -- misrepresenting fields like ``BACKEND_CORS_ORIGINS`` whose
    real default is the factory's return value (e.g. ``[]``). Invoke the
    factory eagerly so the API surfaces the actual default.

    :param field_info: The Pydantic field metadata for the target attribute.
    :type field_info: FieldInfo
    :return: The resolved default value, or :data:`PydanticUndefined` when
        neither ``default`` nor ``default_factory`` is declared.
    :rtype: Any
    """
    if field_info.default is not PydanticUndefined:
        return field_info.default
    factory = field_info.default_factory
    if factory is None:
        return PydanticUndefined
    return factory()


def dump_field_value(field_info: FieldInfo, value: Any) -> Any:
    """Return a JSON-safe representation of ``value`` for the response model.

    Delegates to ``TypeAdapter(_annotated_type(field_info)).dump_python(value, mode='json')``
    so nested Pydantic models, enums, timedeltas, URLs and paths all serialise
    to their canonical JSON shape, including field metadata such as credential-URL
    serializers and constraint annotations. :class:`pydantic.SecretStr` /
    :class:`pydantic.SecretBytes` instances inside the value are automatically
    redacted to ``"**********"`` by Pydantic's secret-aware JSON dump.

    Unordered collections (``set``/``frozenset``) are dumped as a list sorted by
    :func:`_stable_collection_sort_key` so GET order matches the PATCH restore
    path in :func:`_stable_collection_items` across workers.

    When ``field_info.annotation`` is a non-Pydantic-compatible type (e.g.
    ``string.Template``) for which Pydantic cannot build a TypeAdapter, the
    helper returns ``None`` rather than ``str(value)``: a default object
    ``repr`` like ``<string.Template object at 0x7f...>`` is unstable
    (memory-address dependent) and useless for a diffing UI. Operators see
    the field's ``key``, ``description``, ``is_complex`` and ``type`` flags
    and know it cannot be edited via the API.

    :param field_info: The Pydantic field metadata for the target attribute.
    :type field_info: FieldInfo
    :param value: The Python value to serialise.
    :type value: Any
    :return: A JSON-serialisable representation of ``value``, or ``None`` when
        ``value`` is :data:`pydantic_core.PydanticUndefined` (the field has no
        declared default).
    :rtype: Any
    """
    if value is PydanticUndefined:
        return None
    try:
        if isinstance(value, set | frozenset):
            # Dump each element with its concrete runtime type so polymorphic
            # set members (e.g. PagerDuty under BaseAlertProvider) keep their
            # fields; a list[Base...] adapter would strip subclass attributes.
            return [
                TypeAdapter(type(item)).dump_python(item, mode="json")
                for item in sorted(value, key=_stable_collection_sort_key)
            ]
        return TypeAdapter(_annotated_type(field_info)).dump_python(value, mode="json")
    except PydanticSchemaGenerationError:
        return None
