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
    "FieldMarkerKey",
    "FieldMarkers",
    "FieldMetadata",
    "InheritedMarkers",
    "Materializer",
    "MaterializerContext",
    "ReloadClassification",
    "canonical_override_key",
    "chain_has_advanced",
    "chain_has_explicit_not_overridable",
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
    "preserve_patch_secret_value",
    "resolve_nested_field",
    "resolve_nested_field_metadata",
    "resolve_nested_value",
    "unwrap_secrets_for_storage",
]

import functools
import typing
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from string import Template
from types import UnionType
from typing import Annotated, Any, NamedTuple, TYPE_CHECKING, TypedDict, Union

from pydantic import BaseModel, SecretBytes, SecretStr, TypeAdapter, WrapSerializer
from pydantic.errors import PydanticSchemaGenerationError
from pydantic_core import PydanticUndefined

from app.core.settings_override.models import SettingOverride
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


class MaterializerContext(NamedTuple):
    """Bundle the inputs a snapshot materializer may consult.

    A materializer receives the whole context and uses only the members it
    needs. :func:`app.core.settings_override.cache.build_snapshot` constructs
    one per overridden HOT field whose declaration attached a materializer,
    instead of calling :func:`coerce_field_value` directly.

    :param settings_cls: The Pydantic settings class that owns the field.
    :type settings_cls: type[BaseYamlSettings]
    :param field_name: The name of the field being materialized.
    :type field_name: str
    :param field_info: The Pydantic field metadata for the field.
    :type field_info: FieldInfo
    :param raw: The raw, JSON-decoded value stored on the override row.
    :type raw: Any
    """

    settings_cls: type[BaseYamlSettings]
    field_name: str
    field_info: FieldInfo
    raw: Any


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


def is_hot_reloadable(settings_cls: type[BaseModel], field_name: str) -> bool:
    """Return whether the given field is marked HOT on the given settings class.

    Accepts any Pydantic ``BaseModel`` subclass, not just ``BaseYamlSettings``:
    the nested-override resolver consults this predicate against nested
    submodels (e.g. ``SessionOptions``) when classifying leaf fields.

    :param settings_cls: The Pydantic model class to inspect.
    :type settings_cls: type[BaseModel]
    :param field_name: The name of the field to check.
    :type field_name: str
    :return: ``True`` when ``field_name`` exists on ``settings_cls`` and is
        marked with ``{"reload": ReloadClassification.HOT}`` via
        :func:`app.core.utils.pydantic.field_with_metadata` or the class overlay.
    :rtype: bool
    """
    field = settings_cls.model_fields.get(field_name)
    if field is None:
        return False
    markers = _effective_field_markers(
        field, owner_cls=settings_cls, field_name=field_name
    )
    return markers.get(FieldMarkerKey.RELOAD) == ReloadClassification.HOT


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

    :param field_info: The Pydantic field metadata to classify.
    :param owner_cls: The class owning ``field_info``, for overlay lookup.
    :param field_name: The field's name on ``owner_cls``, for overlay lookup.
    :return: The field's reload classification.
    :rtype: ReloadClassification
    """
    value = _effective_field_markers(field_info, owner_cls, field_name).get(
        FieldMarkerKey.RELOAD
    )
    if value in {ReloadClassification.HOT, ReloadClassification.NESTED_ONLY}:
        return value
    return ReloadClassification.NOT_OVERRIDABLE


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
) -> Any:
    """Turn a raw override value into its typed snapshot value.

    Routes through the field's declared materializer when present, otherwise the
    default :func:`coerce_field_value` coercion. Shared by snapshot building
    (:func:`app.core.settings_override.cache.build_snapshot`) and the settings
    API PATCH validation so both accept exactly the same override payloads -- a
    materializer-backed field (``PROVIDERS``, ``FOOTER_TEMPLATE``)
    would otherwise be accepted on snapshot load but rejected by the API.

    :param settings_cls: The Pydantic settings class that owns the field.
    :type settings_cls: type[BaseYamlSettings]
    :param field_name: The name of the field being materialized.
    :type field_name: str
    :param field_info: The Pydantic field metadata for the field.
    :type field_info: FieldInfo
    :param raw: The raw, JSON-decoded override value.
    :type raw: Any
    :return: The materialized (or coerced) typed value.
    :rtype: Any
    :raises ValidationError: If coercion or the materializer's validation fails.
    :raises ValueError: If a ``mode="before"`` validator rejects ``raw``.
    """
    materializer = field_materializer(settings_cls, field_name)
    if materializer is not None:
        return materializer(
            MaterializerContext(settings_cls, field_name, field_info, raw)
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
    settings_cls: type[BaseModel], field_name: str
) -> bool:
    """Return whether ``field_name`` accepts nested-child overrides.

    ``True`` iff the field's classification is :attr:`ReloadClassification.HOT`
    OR :attr:`ReloadClassification.NESTED_ONLY`. ``False`` for unknown fields
    and for fields classified ``NOT_OVERRIDABLE``.

    Used by :func:`app.core.settings_override.api.routes._validate_patch_body`
    and :func:`app.core.settings_override.cache.build_snapshot` to gate
    ``__``-delimited keys at the parent level before walking into the nested
    resolver.

    :param settings_cls: The Pydantic settings class declaring the field.
    :type settings_cls: type[BaseModel]
    :param field_name: The top-level field name.
    :type field_name: str
    :return: ``True`` iff nested-child overrides may target this field.
    :rtype: bool
    """
    info = settings_cls.model_fields.get(field_name)
    if info is None:
        return False
    markers = _effective_field_markers(
        info, owner_cls=settings_cls, field_name=field_name
    )
    return markers.get(FieldMarkerKey.RELOAD) in {
        ReloadClassification.HOT,
        ReloadClassification.NESTED_ONLY,
    }


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


def coerce_nested_field_value(
    settings_cls: type[BaseModel],
    key: str,
    raw: Any,
) -> tuple[tuple[str, ...], Any]:
    """Resolve ``key`` to a nested attribute chain and coerce ``raw`` to the leaf type.

    Combines :func:`resolve_nested_field` and :func:`coerce_field_value` so the
    cache and API layers have one entry point for the full nested-row coercion
    contract. A path whose leaf *or any intermediate* is explicitly classified
    ``NOT_OVERRIDABLE`` is rejected by raising :class:`KeyError`, matching the
    unresolvable-path contract so the caller's existing ``except KeyError``
    branch logs and skips uniformly.

    :param settings_cls: The top-level Pydantic settings class.
    :type settings_cls: type[BaseModel]
    :param key: The override row's ``__``-delimited key.
    :type key: str
    :param raw: The raw JSON-decoded value to coerce.
    :type raw: Any
    :return: ``((canonical_segment, ...), coerced_value)``.
    :rtype: tuple[tuple[str, ...], Any]
    :raises KeyError: If the path is unresolvable on ``settings_cls`` or any
        segment along it is explicitly classified ``NOT_OVERRIDABLE``.
    :raises ValidationError: If ``raw`` cannot be coerced to the leaf's type.
    """
    resolved = _resolve_nested_segments(settings_cls, key)
    if resolved is None:
        raise KeyError(key)
    if any(
        is_explicit_not_overridable(info, owner_cls=owner, field_name=name)
        for owner, name, info in resolved
    ):
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
    fields so nested model attributes are inspected too.

    :param annotation: The type annotation to walk.
    :type annotation: Any
    :return: An iterator over the referenced type arguments.
    :rtype: Iterator[Any]
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


#: Pydantic's default JSON dump mask for :class:`~pydantic.SecretStr` /
#: :class:`~pydantic.SecretBytes`. Distinct from
#: :data:`~app.core.utils.fields.CREDENTIAL_URL_MASK` (``"****"``).
SECRET_STR_MASK = "**********"  # noqa: S105


def _field_contains_secret(field_info: FieldInfo) -> bool:
    """Return whether ``field_info`` exposes a Pydantic secret anywhere in its annotation.

    Walks the annotation recursively, descending into nested
    :class:`pydantic.BaseModel` subclasses, looking for
    :class:`pydantic.SecretStr` or :class:`pydantic.SecretBytes`.

    :param field_info: The Pydantic field metadata for the target attribute.
    :type field_info: FieldInfo
    :return: ``True`` when a secret type is reachable from the annotation.
    :rtype: bool
    """
    secret_types = (SecretStr, SecretBytes)
    for arg in _iter_type_arguments(field_info.annotation):
        if isinstance(arg, type) and issubclass(arg, secret_types):
            return True
    return False


def _unwrap_secret_value(current: Any) -> str | bytes | None:
    """Return the plain secret from a ``SecretStr``/``SecretBytes``, else ``None``.

    :param current: A live stored value that may be a Pydantic secret wrapper.
    :type current: Any
    :return: ``get_secret_value()`` when ``current`` is a secret instance;
        ``None`` otherwise.
    :rtype: str | bytes | None
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
    :type value: Any
    :return: ``value`` with every secret wrapper replaced by its plain
        ``get_secret_value()`` (``SecretBytes`` decoded as UTF-8 with
        surrogateescape so the result stays JSON-serialisable).
    :rtype: Any
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

    :param field_info: The Pydantic field metadata for the target attribute.
    :type field_info: FieldInfo
    :param current: The effective stored value (model, mapping, or secret wrapper).
    :type current: Any
    :param incoming: The value submitted in the PATCH body.
    :type incoming: Any
    :return: ``incoming`` with any masked credentials restored from ``current``.
    :rtype: Any
    """
    if is_credential_url_field(field_info):
        if isinstance(incoming, str) and current is not None:
            value = preserve_credential_url_password(str(current), incoming)
        else:
            value = incoming
    else:
        parent_cls = annotation_pydantic_class(field_info.annotation)
        if parent_cls and isinstance(incoming, Mapping):
            value = preserve_credential_urls_in_model_payload(
                parent_cls, current, incoming
            )
        else:
            value = incoming
    return preserve_patch_secret_value(field_info, current, value)


def _annotation_is_secret_valued_dict(annotation: Any) -> bool:
    """Return whether ``annotation`` is a ``dict`` whose values are secrets.

    Unwraps optional/union wrappers at the top level only (does not descend into
    nested :class:`~pydantic.BaseModel` fields), matching
    ``dict[str, SecretStr]`` / ``dict[str, SecretBytes]`` shapes.

    :param annotation: The field annotation to inspect.
    :type annotation: Any
    :return: ``True`` when the annotation is a secret-valued mapping type.
    :rtype: bool
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


def _preserve_masked_secret_scalar(current: Any, incoming: Any) -> Any:
    """Restore a stored secret when ``incoming`` equals :data:`SECRET_STR_MASK`.

    :param current: The live stored value, possibly a ``SecretStr``/``SecretBytes``.
    :type current: Any
    :param incoming: The PATCH value that may be the secret JSON mask.
    :type incoming: Any
    :return: The unwrapped stored secret when ``incoming`` is the mask and
        ``current`` is a secret wrapper; otherwise ``incoming`` unchanged.
    :rtype: Any
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
    :type current: Any
    :param incoming: The PATCH mapping that may contain mask literals.
    :type incoming: Mapping[str, Any]
    :return: A copy of ``incoming`` with masked keys restored from ``current``.
    :rtype: dict[str, Any]
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


def preserve_secrets_in_model_payload(
    model_cls: type[BaseModel],
    current: Any,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Restore masked SecretStr/SecretBytes values inside a nested-model PATCH payload.

    :param model_cls: The Pydantic model whose fields ``incoming`` addresses.
    :type model_cls: type[BaseModel]
    :param current: The live stored model or mapping fingerprint.
    :type current: Any
    :param incoming: The PATCH mapping for this model.
    :type incoming: Mapping[str, Any]
    :return: A copy of ``incoming`` with masked secrets restored from ``current``.
    :rtype: dict[str, Any]
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
    models and ``dict[str, SecretStr]`` / ``dict[str, SecretBytes]`` payloads.

    :param field_info: The Pydantic field metadata for the target attribute.
    :type field_info: FieldInfo
    :param current: The effective stored value (model, mapping, or secret wrapper).
    :type current: Any
    :param incoming: The value submitted in the PATCH body.
    :type incoming: Any
    :return: ``incoming`` with any masked secrets restored from ``current``.
    :rtype: Any
    """
    parent_cls = annotation_pydantic_class(field_info.annotation)
    if parent_cls and isinstance(incoming, Mapping):
        return preserve_secrets_in_model_payload(parent_cls, current, incoming)
    if _annotation_is_secret_valued_dict(field_info.annotation) and isinstance(
        incoming, Mapping
    ):
        return _preserve_secrets_in_dict_payload(current, incoming)
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
    ``NOT_OVERRIDABLE`` when the leaf **or any intermediate in its chain** is
    explicitly :func:`not_overridable_field`-marked -- the same chain check that
    gates PATCH/DELETE, so the reported classification matches what an override
    would actually be allowed to do. ``is_advanced`` is likewise chain-resolved
    via :func:`chain_has_advanced`, so a leaf inherits the flag from an advanced
    parent.

    :param settings_cls: The top-level Pydantic settings class.
    :type settings_cls: type[BaseModel]
    :param key: The ``__``-delimited override key.
    :type key: str
    :return: The synthesised leaf metadata, or ``None`` when ``key`` does not
        resolve to a nested field.
    :rtype: FieldMetadata | None
    """
    resolved = resolve_nested_field(settings_cls, key)
    if resolved is None:
        return None
    _chain, leaf_info = resolved
    reload = (
        ReloadClassification.NOT_OVERRIDABLE
        if chain_has_explicit_not_overridable(settings_cls, key)
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
        return TypeAdapter(_annotated_type(field_info)).dump_python(value, mode="json")
    except PydanticSchemaGenerationError:
        return None
