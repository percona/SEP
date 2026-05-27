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

__all__ = [
    "FieldMetadata",
    "ReloadClassification",
    "coerce_field_value",
    "dump_field_value",
    "hot_field",
    "hot_field_names",
    "is_hot_reloadable",
    "iter_class_fields",
]

import typing
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from types import UnionType
from typing import Annotated, Any, Union

from pydantic import BaseModel, SecretBytes, SecretStr, TypeAdapter
from pydantic.errors import PydanticSchemaGenerationError
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from app.core.config import BaseYamlSettings
from app.core.utils.pydantic import CustomFieldMetadata, field_with_metadata


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


def hot_field(default: Any, **kwargs: Any) -> FieldInfo:
    """Declare a settings field as HOT-reloadable from a DB override.

    Thin wrapper over :func:`app.core.utils.pydantic.field_with_metadata` that
    attaches ``{"reload": ReloadClassification.HOT}`` so the field is picked up
    by :func:`is_hot_reloadable` and snapshot building.

    :param default: The field's default value, passed positionally to ``Field``.
    :type default: Any
    :param kwargs: Additional keyword arguments forwarded to ``Field``.
    :type kwargs: Any
    :return: A Pydantic field marked with the HOT reload classification.
    :rtype: FieldInfo
    """
    return field_with_metadata(
        default, metadata={"reload": ReloadClassification.HOT}, **kwargs
    )


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
            default=field.default,
            description=field.description,
            reload=(
                ReloadClassification.HOT
                if is_hot_reloadable(settings_cls, name)
                else ReloadClassification.NOT_OVERRIDABLE
            ),
            is_secret=_field_contains_secret(field),
            is_complex=_field_is_complex(field.annotation),
        )


def dump_field_value(field_info: FieldInfo, value: Any) -> Any:
    """Return a JSON-safe representation of ``value`` for the response model.

    Delegates to ``TypeAdapter(field.annotation).dump_python(value, mode='json')``
    so nested Pydantic models, enums, timedeltas, URLs and paths all serialise
    to their canonical JSON shape. :class:`pydantic.SecretStr` /
    :class:`pydantic.SecretBytes` instances inside the value are automatically
    redacted to ``"**********"`` by Pydantic's secret-aware JSON dump.

    When ``field_info.annotation`` is a non-Pydantic-compatible type (e.g.
    ``string.Template``) for which Pydantic cannot build a TypeAdapter, the
    helper falls back to ``str(value)`` so the LIST/GET responses surface the
    field instead of returning a 500 to the operator.

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
        return str(value)
