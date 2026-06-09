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
    "FieldMetadata",
    "Materializer",
    "MaterializerContext",
    "ReloadClassification",
    "canonical_override_key",
    "chain_has_explicit_not_overridable",
    "coerce_field_value",
    "coerce_nested_field_value",
    "dump_field_value",
    "field_materializer",
    "field_reload_classification",
    "hot_field",
    "hot_field_names",
    "is_explicit_not_overridable",
    "is_hot_reloadable",
    "is_nested_overridable_parent",
    "iter_class_fields",
    "materialize_fingerprint",
    "materialize_override_value",
    "materialize_template",
    "materialize_via_owning_model",
    "nested_overridable_field",
    "nested_overridable_field_names",
    "not_overridable_field",
    "override_keys_for_rows",
    "resolve_nested_field",
    "resolve_nested_field_metadata",
    "resolve_nested_value",
]

import functools
import typing
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from string import Template
from types import UnionType
from typing import Annotated, Any, NamedTuple, TYPE_CHECKING, Union

from pydantic import BaseModel, SecretBytes, SecretStr, TypeAdapter
from pydantic.errors import PydanticSchemaGenerationError
from pydantic_core import PydanticUndefined

from app.core.settings_override.models import SettingOverride
from app.core.settings_override.proxy import OverridableSettingsProxy
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


def hot_field(
    default: Any, *, materializer: Materializer | None = None, **kwargs: Any
) -> FieldInfo:
    """Declare a settings field as HOT-reloadable from a DB override.

    Thin wrapper over :func:`app.core.utils.pydantic.field_with_metadata` that
    attaches ``{"reload": ReloadClassification.HOT}`` so the field is picked up
    by :func:`is_hot_reloadable` and snapshot building. When ``materializer`` is
    supplied it rides the same metadata channel under the ``"materializer"`` key
    and :func:`app.core.settings_override.cache.build_snapshot` invokes it in
    place of the default :func:`coerce_field_value` coercion -- used for fields
    whose snapshot value cannot be produced by a plain ``TypeAdapter`` (a
    before-validator must run, the type is not Pydantic-serialisable, or a plain
    fingerprint must be stored for diff stability).

    :param default: The field's default value, passed positionally to ``Field``.
    :type default: Any
    :param materializer: An optional callable that converts the raw override
        value into the snapshot value. Receives a :class:`MaterializerContext`.
    :type materializer: Materializer | None
    :param kwargs: Additional keyword arguments forwarded to ``Field``.
    :type kwargs: Any
    :return: A Pydantic field marked with the HOT reload classification.
    :rtype: FieldInfo
    """
    reload_metadata = {"reload": ReloadClassification.HOT}
    metadata = (
        {**reload_metadata, "materializer": materializer}
        if materializer is not None
        else reload_metadata
    )
    return field_with_metadata(default, metadata=metadata, **kwargs)


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
        :func:`app.core.utils.pydantic.field_with_metadata`.
    :rtype: bool
    """
    field = settings_cls.model_fields.get(field_name)
    if field is None:
        return False
    metadata = CustomFieldMetadata.field_to_dict(field)
    return metadata.get("reload") == ReloadClassification.HOT


def field_reload_classification(field_info: FieldInfo) -> ReloadClassification:
    """Return the reload classification attached to a single field.

    Reads the ``{"reload": ...}`` metadata set by :func:`hot_field`,
    :func:`nested_overridable_field`, or :func:`not_overridable_field`. Any
    field with no recognised marker is reported ``NOT_OVERRIDABLE``.

    Unlike :func:`is_hot_reloadable` (which takes a settings class plus a field
    name), this operates on a :class:`FieldInfo` directly so callers can
    classify a nested leaf resolved out of a submodel.

    :param field_info: The Pydantic field metadata to classify.
    :type field_info: FieldInfo
    :return: The field's reload classification.
    :rtype: ReloadClassification
    """
    value = CustomFieldMetadata.field_to_dict(field_info).get("reload")
    if value in {ReloadClassification.HOT, ReloadClassification.NESTED_ONLY}:
        return value
    return ReloadClassification.NOT_OVERRIDABLE


def is_explicit_not_overridable(field_info: FieldInfo) -> bool:
    """Return whether a field carries an *explicit* ``NOT_OVERRIDABLE`` marker.

    Distinct from ``field_reload_classification(...) == NOT_OVERRIDABLE``: an
    unmarked field reports ``NOT_OVERRIDABLE`` from
    :func:`field_reload_classification` (the default top-level classification),
    but a *nested leaf* under a nested-overridable parent inherits HOT unless it
    is explicitly :func:`not_overridable_field`-marked. This predicate is
    ``True`` only for the explicit marker, so unmarked nested leaves stay
    overridable.

    :param field_info: The Pydantic field metadata to inspect.
    :type field_info: FieldInfo
    :return: ``True`` iff the field has an explicit ``NOT_OVERRIDABLE`` marker.
    :rtype: bool
    """
    return (
        CustomFieldMetadata.field_to_dict(field_info).get("reload")
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
    same custom-metadata channel :func:`is_hot_reloadable` reads ``"reload"``
    from.

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
    return CustomFieldMetadata.field_to_dict(field).get("materializer")


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


def materialize_fingerprint(ctx: MaterializerContext) -> Any:
    """Materialize a plain JSON config fingerprint instead of a live instance.

    Coerces ``raw`` to the field's declared type, then stores only its
    ``model_dump(mode="json")`` -- a plain dict carrying no private attributes.
    Two snapshots built from the same override therefore compare equal, which a
    live model instance with per-instance private attributes (a ``ContextVar``,
    an aiohttp session) would not. The live resource is owned by a lifecycle
    holder; the snapshot carries only the diff-stable config fingerprint.

    :param ctx: The materialization context.
    :type ctx: MaterializerContext
    :return: A JSON-safe ``dict`` fingerprint of the coerced value.
    :rtype: Any
    :raises ValidationError: If ``raw`` cannot be coerced to the declared type.
    """
    return coerce_field_value(ctx.field_info, ctx.raw).model_dump(mode="json")


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
    materializer-backed field (``PROVIDERS``, ``FOOTER_TEMPLATE``, ``NOMAD``)
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


def nested_overridable_field(default: Any, **kwargs: Any) -> FieldInfo:
    """Declare a nested-model field whose children may be overridden by DB rows.

    The parent field itself rejects whole-object override
    (``PATCH {parent: {...}}`` → 422). Nested children (``parent__leaf``) are
    accepted, defaulting to HOT-inherit unless the leaf is explicitly
    :func:`not_overridable_field`-marked.

    Mirrors :func:`hot_field`'s call signature; attaches
    ``{"reload": ReloadClassification.NESTED_ONLY}``.

    :param default: The field's default value, passed positionally to ``Field``.
    :type default: Any
    :param kwargs: Additional keyword arguments forwarded to ``Field``.
    :type kwargs: Any
    :return: A Pydantic field marked NESTED_ONLY.
    :rtype: FieldInfo
    """
    return field_with_metadata(
        default,
        metadata={"reload": ReloadClassification.NESTED_ONLY},
        **kwargs,
    )


def not_overridable_field(default: Any, **kwargs: Any) -> FieldInfo:
    """Declare a settings field as explicitly NOT overridable from a DB row.

    Mirrors :func:`hot_field` but attaches
    ``{"reload": ReloadClassification.NOT_OVERRIDABLE}``. Use under a HOT or
    NESTED_ONLY parent when a specific nested leaf must NOT inherit the
    parent's HOT-by-default child semantics.

    :param default: The field's default value, passed positionally to ``Field``.
    :type default: Any
    :param kwargs: Additional keyword arguments forwarded to ``Field``.
    :type kwargs: Any
    :return: A Pydantic field marked NOT_OVERRIDABLE.
    :rtype: FieldInfo
    """
    return field_with_metadata(
        default,
        metadata={"reload": ReloadClassification.NOT_OVERRIDABLE},
        **kwargs,
    )


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
    metadata = CustomFieldMetadata.field_to_dict(info)
    return metadata.get("reload") in {
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
        if CustomFieldMetadata.field_to_dict(info).get("reload")
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
) -> list[tuple[str, FieldInfo]] | None:
    """Resolve every ``__`` segment of ``key`` to its ``(canonical_name, FieldInfo)``.

    Walks one segment at a time, descending into nested Pydantic models. Returns
    ``None`` when any segment is unresolvable, the path hits a non-Pydantic
    intermediate, or the key is empty. The list preserves order from the
    top-level parent down to the leaf, so callers can inspect intermediate
    fields (e.g. for an explicit ``not_overridable_field`` marker) and not just
    the leaf.

    :param settings_cls: The top-level Pydantic settings class.
    :type settings_cls: type[BaseModel]
    :param key: The ``__``-delimited override key.
    :type key: str
    :return: One ``(canonical_name, FieldInfo)`` per segment, or ``None``.
    :rtype: list[tuple[str, FieldInfo]] | None
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
        resolved_chain.append((canonical, info))
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
    return tuple(name for name, _ in resolved), resolved[-1][1]


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
    return any(is_explicit_not_overridable(info) for _, info in resolved)


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
    if any(is_explicit_not_overridable(info) for _, info in resolved):
        raise KeyError(key)
    chain = tuple(name for name, _ in resolved)
    leaf_info = resolved[-1][1]
    return chain, coerce_field_value(leaf_info, raw)


def resolve_nested_value(
    *,
    settings_cls: type[BaseModel],
    proxy: OverridableSettingsProxy,
    key: str,
) -> tuple[FieldInfo, Any]:
    """Return the leaf field metadata and current value for a nested key.

    Walks the proxy attribute chain segment by segment using the resolver's
    canonical (case-corrected) names, so the returned value reflects the merged
    snapshot copy when an override is active and the YAML/env value otherwise.

    :param settings_cls: The Pydantic settings class the key belongs to.
    :type settings_cls: type[BaseModel]
    :param proxy: The proxy whose attribute chain yields the current value.
    :type proxy: OverridableSettingsProxy
    :param key: The ``__``-delimited nested key.
    :type key: str
    :return: A ``(leaf_FieldInfo, current_value)`` pair.
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
        # Optional intermediate may be None before any override; short-circuit
        # instead of raising.
        current = getattr(current, segment, None)
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
    """Introspected metadata for a single settings field.

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
    """

    key: str
    annotation: Any
    default: Any
    description: str | None
    reload: ReloadClassification
    is_secret: bool
    is_complex: bool


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
    ``is_secret`` (whether the field's type contains a SecretStr anywhere) and
    ``is_complex`` (whether the type is a nested Pydantic model).

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
            reload=field_reload_classification(field),
            is_secret=_field_contains_secret(field),
            is_complex=_field_is_complex(field.annotation),
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
    ``NOT_OVERRIDABLE`` only when the leaf is explicitly
    :func:`not_overridable_field`-marked.

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
        if is_explicit_not_overridable(leaf_info)
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
    )


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

    Delegates to ``TypeAdapter(field.annotation).dump_python(value, mode='json')``
    so nested Pydantic models, enums, timedeltas, URLs and paths all serialise
    to their canonical JSON shape. :class:`pydantic.SecretStr` /
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
        return TypeAdapter(field_info.annotation).dump_python(value, mode="json")
    except PydanticSchemaGenerationError:
        return None
