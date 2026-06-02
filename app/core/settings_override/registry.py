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
    "coerce_field_value",
    "dump_field_value",
    "field_materializer",
    "hot_field",
    "hot_field_names",
    "is_hot_reloadable",
    "iter_class_fields",
    "materialize_fingerprint",
    "materialize_override_value",
    "materialize_template",
    "materialize_via_owning_model",
]

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

from app.core.utils.pydantic import CustomFieldMetadata, field_with_metadata

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
    :vartype HOT: str
    :cvar NOT_OVERRIDABLE: Field is not overridable from the database; YAML
        and environment variables remain the only sources of truth.
    :vartype NOT_OVERRIDABLE: str
    """

    HOT = "hot"
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


def is_hot_reloadable(settings_cls: type[BaseYamlSettings], field_name: str) -> bool:
    """Return whether the given field is marked HOT on the given settings class.

    :param settings_cls: The Pydantic settings class to inspect.
    :type settings_cls: type[BaseYamlSettings]
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
            reload=(
                ReloadClassification.HOT
                if is_hot_reloadable(settings_cls, name)
                else ReloadClassification.NOT_OVERRIDABLE
            ),
            is_secret=_field_contains_secret(field),
            is_complex=_field_is_complex(field.annotation),
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
