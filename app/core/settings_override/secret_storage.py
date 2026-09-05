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

"""Encrypt and decrypt the secret-typed leaves of a stored override value.

Override rows persist through a JSON column, and
:func:`~app.core.settings_override.registry.unwrap_secrets_for_storage` strips
the :class:`~pydantic.SecretStr` wrapper before the value is written, so the
credential would otherwise reach the database in the clear. The walker here maps
a settings field's *annotation* onto the stored JSON positionally and transforms
the leaves whose annotation is a Pydantic secret type.

Which leaves are secret is decided **only** from the annotation, never from the
stored JSON's shape or content. A materializer-backed field stores the client's
raw payload rather than the coerced model, and is handled on the same terms as a
plain one because of that.

Where two candidate models at one JSON position declare a field of the same
name and only one types it as a secret, the secret-typed annotation wins, so the
value is encrypted rather than stored in the clear. No such collision exists in
``app/`` today.

A credential-bearing URL is **not** covered. ``StrCredentialHttpUrl`` and
``CredentialHttpUrl`` carry no secret type in their annotation, so a password
embedded in ``PMMSettings.endpoint`` or ``DeliveryPlanInputs.endpoint`` is stored
in the clear beside an ``api_key`` this module encrypts, even though
:func:`~app.core.settings_override.registry.is_credential_url_field` already
redacts it on every read surface.
"""

from __future__ import annotations

__all__ = [
    "decrypt_secret_leaves",
    "encrypt_secret_leaves",
    "reencrypt_secret_leaves",
]

import typing
from collections.abc import Callable, Collection, Mapping
from types import UnionType
from typing import Any, TYPE_CHECKING, Union

from pydantic import BaseModel, SecretBytes, SecretStr

from app.core.encryption import decrypt, encrypt, is_encrypted
from app.core.settings_override.registry import (
    annotation_contains_secret,
    resolve_nested_field,
)

if TYPE_CHECKING:
    from app.core.config import BaseYamlSettings

_SECRET_TYPES = (SecretStr, SecretBytes)


def encrypt_secret_leaves(
    settings_cls: type[BaseYamlSettings],
    key: str,
    value: Any,
) -> Any:
    """Return ``value`` with every secret-typed leaf encrypted.

    Encrypts unconditionally, which is what the write path needs: the values
    reaching it are freshly coerced from the request body, and the one that is
    reused rather than submitted (a secret restored because the client sent the
    redaction mask back) is read from the decrypted snapshot. Deciding
    structurally whether a leaf "looks encrypted" would misread a credential
    that happens to be base64 as ciphertext and store it in the clear.

    :param settings_cls: The settings class owning ``key``.
    :param key: The override row's key, ``__``-delimited for a nested leaf.
    :param value: The JSON-storable value about to be persisted.
    :return: A value of the same shape with its secret leaves encrypted.
    """
    return _transform_secret_leaves(
        _annotation_for_key(settings_cls, key), value, encrypt
    )


def reencrypt_secret_leaves(
    settings_cls: type[BaseYamlSettings],
    key: str,
    value: Any,
) -> Any:
    """Return ``value`` with every not-yet-encrypted secret leaf encrypted.

    The idempotent variant the re-encryption migrations need, where the column
    genuinely may already hold ciphertext. A leaf
    :func:`~app.core.encryption.is_encrypted` accepts is left byte-identical, so
    a second run rewrites nothing and ciphertext written under a different
    ``ENCRYPTION_KEY`` is never re-encrypted, which would destroy the only copy
    of its plaintext.

    ``is_encrypted`` is structural, so a legacy plaintext secret that is itself
    a well-formed Fernet token is skipped and stays in the clear. Attempting a
    decrypt to tell the two apart is not an option: a failure there cannot
    separate that case from the foreign-key one, and guessing wrong on the
    second destroys data. Only the write path is free of the ambiguity, and it
    uses :func:`encrypt_secret_leaves`.

    :param settings_cls: The settings class owning ``key``.
    :param key: The override row's key, ``__``-delimited for a nested leaf.
    :param value: The stored value being rewritten in place.
    :return: A value of the same shape with its plaintext secret leaves encrypted.
    """
    return _transform_secret_leaves(
        _annotation_for_key(settings_cls, key),
        value,
        lambda leaf: leaf if is_encrypted(leaf) else encrypt(leaf),
    )


def decrypt_secret_leaves(
    settings_cls: type[BaseYamlSettings],
    key: str,
    value: Any,
) -> Any:
    """Return ``value`` with every secret-typed leaf decrypted.

    A leaf that is not ciphertext is passed through unchanged, so a row written
    before its track's re-encryption migration ran keeps resolving.

    :param settings_cls: The settings class owning ``key``.
    :param key: The override row's key, ``__``-delimited for a nested leaf.
    :param value: The JSON value read out of the override row.
    :return: A value of the same shape with its secret leaves in plaintext.
    :raises DecryptionError: If a leaf is ciphertext the configured
        ``ENCRYPTION_KEY`` cannot decrypt.
    """
    return _transform_secret_leaves(
        _annotation_for_key(settings_cls, key),
        value,
        lambda leaf: decrypt(leaf) if is_encrypted(leaf) else leaf,
    )


def _annotation_for_key(settings_cls: type[BaseYamlSettings], key: str) -> Any:
    """Return the annotation of the field ``key`` overrides, or ``None``.

    :param settings_cls: The settings class owning ``key``.
    :param key: The override row's key, ``__``-delimited for a nested leaf.
    :return: The leaf annotation, or ``None`` when ``key`` resolves to no field.
    """
    if "__" in key:
        resolved = resolve_nested_field(settings_cls, key)
        return None if resolved is None else resolved[1].annotation
    field_info = settings_cls.model_fields.get(key)
    return None if field_info is None else field_info.annotation


def _positional_args(annotation: Any) -> list[Any]:
    """Return the types a value at this JSON position may take, in declaration order.

    Strips :data:`~typing.Annotated` wrappers, flattens unions and drops
    ``NoneType``. Unlike the recursive walk behind
    :func:`~app.core.settings_override.registry.annotation_contains_secret`
    this does **not** descend through a model into its fields: a value at one
    position cannot be an arbitrary attribute of a model reachable from it.

    Order is part of the contract rather than an accident of the traversal:
    :func:`_first_secret_bearing` resolves a contested position by taking the
    first candidate that reaches a secret, so a union's members have to arrive
    in the order the annotation declares them. Pushing them reversed onto a
    LIFO stack is what preserves that.

    :param annotation: The annotation to flatten.
    :return: The candidate types for this position, in declaration order.
    """
    flattened: list[Any] = []
    stack = [annotation]
    while stack:
        current = stack.pop()
        if current is None or current is type(None):
            continue
        if hasattr(current, "__metadata__"):
            stack.append(typing.get_args(current)[0])
            continue
        if typing.get_origin(current) in {Union, UnionType}:
            stack.extend(reversed(typing.get_args(current)))
            continue
        flattened.append(current)
    return flattened


def _is_secret_position(positional: list[Any]) -> bool:
    """Return whether the value at this position is itself a secret.

    :param positional: The candidate types for one JSON position.
    :return: ``True`` when one of them is a Pydantic secret type.
    """
    return any(
        isinstance(arg, type) and issubclass(arg, _SECRET_TYPES) for arg in positional
    )


def _first_secret_bearing(candidates: list[Any]) -> Any:
    """Return the first candidate reaching a secret, or ``None`` when none does.

    Two annotations can compete for one JSON position: a union of container
    types, or the same field name declared by two candidate models. Preferring
    the secret-bearing one keeps the walker conservative, so a value that may be
    a credential is encrypted rather than stored in the clear.

    Returning ``None`` rather than an arbitrary survivor is what makes the
    container branches fall through to the model branch: ``dict[str, str] |
    Inner`` would otherwise resolve to the mapping's plain ``str`` values and
    never look inside ``Inner`` for its secret.

    :param candidates: The competing annotations, in declaration order.
    :return: The first secret-bearing annotation, or ``None``.
    """
    return next(
        (
            candidate
            for candidate in candidates
            if annotation_contains_secret(candidate)
        ),
        None,
    )


def _is_mapping_origin(origin: Any) -> bool:
    """Return whether ``origin`` is a mapping type.

    Tested by subclass rather than against a list of names so every mapping the
    codebase can annotate is covered. ``defaultdict`` and ``OrderedDict`` are
    both live override-field annotations today.

    :param origin: The generic origin to classify.
    :return: ``True`` for a mapping origin.
    """
    return isinstance(origin, type) and issubclass(origin, Mapping)


def _is_collection_origin(origin: Any) -> bool:
    """Return whether ``origin`` is a non-mapping, non-string collection type.

    :param origin: The generic origin to classify.
    :return: ``True`` for a list/set/tuple-like origin.
    """
    return (
        isinstance(origin, type)
        and issubclass(origin, Collection)
        and not issubclass(origin, Mapping | str | bytes)
    )


def _mapping_value_annotation(positional: list[Any]) -> Any:
    """Return the annotation of a mapping's values at this position, or ``None``.

    :param positional: The candidate types for one JSON position.
    :return: The value annotation of a secret-bearing mapping candidate.
    """
    candidates = [
        typing.get_args(arg)[-1]
        for arg in positional
        if _is_mapping_origin(typing.get_origin(arg)) and len(typing.get_args(arg)) > 1
    ]
    return _first_secret_bearing(candidates)


def _element_annotation(positional: list[Any], index: int) -> Any:
    """Return the annotation of the item at ``index``, or ``None``.

    A fixed-length ``tuple`` annotates each slot separately, so its items are
    resolved per index; every other collection, and a variadic
    ``tuple[X, ...]``, annotates all items with one type.

    :param positional: The candidate types for the enclosing JSON position.
    :param index: The item's position within the stored array.
    :return: The element annotation of a secret-bearing collection candidate.
    """
    candidates: list[Any] = []
    for arg in positional:
        origin = typing.get_origin(arg)
        args = typing.get_args(arg)
        if not (_is_collection_origin(origin) and args):
            continue
        if origin is tuple and Ellipsis not in args:
            if index < len(args):
                candidates.append(args[index])
            continue
        candidates.append(args[0])
    return _first_secret_bearing(candidates)


def _candidate_models(positional: list[Any]) -> list[type[BaseModel]]:
    """Return every model a value at this position may validate as.

    Concrete subclasses are included recursively, so a polymorphic collection
    annotated with its base (``set[BaseAlertProvider]``) reaches the subclass
    that actually declares the secret field. Only subclasses Python has already
    imported are visible.

    :param positional: The candidate types for one JSON position.
    :return: The reachable model classes, most general first.
    """
    models: list[type[BaseModel]] = []
    seen: set[int] = set()
    queue = list(positional)
    while queue:
        current = queue.pop(0)
        if not (isinstance(current, type) and issubclass(current, BaseModel)):
            continue
        if id(current) in seen:
            continue
        seen.add(id(current))
        models.append(current)
        queue.extend(current.__subclasses__())
    return models


def _field_annotation(models: list[type[BaseModel]], json_key: str) -> Any:
    """Return the annotation ``json_key`` maps to across ``models``, or ``None``.

    Field names are matched case-folded because stored key casing is
    client-controlled for a materializer-backed field: the provider models are
    ``BaseCaseInsensitiveModel`` subclasses, so ``routing_key`` and
    ``ROUTING_KEY`` are both accepted and whichever the client sent is what was
    persisted.

    :param models: The candidate models for the enclosing JSON object.
    :param json_key: The stored key to resolve.
    :return: The matching field's annotation, or ``None`` when nothing matches.
    """
    folded = json_key.casefold()
    matches = [
        field.annotation
        for model in models
        for name, field in model.model_fields.items()
        if name.casefold() == folded
    ]
    secret_bearing = _first_secret_bearing(matches)
    if secret_bearing is not None:
        return secret_bearing
    return matches[0] if matches else None


def _transform_secret_leaves(
    annotation: Any,
    value: Any,
    transform: Callable[[str], str],
) -> Any:
    """Return ``value`` with ``transform`` applied to every secret-typed leaf.

    Returns new containers and never mutates ``value``. A subtree whose
    annotation reaches no secret is returned by identity.

    :param annotation: The annotation of the JSON position ``value`` occupies,
        or ``None`` when the position could not be resolved.
    :param value: The stored value at that position.
    :param transform: The leaf transformation to apply.
    :return: The transformed value.
    """
    if annotation is None or not annotation_contains_secret(annotation):
        return value
    positional = _positional_args(annotation)
    if _is_secret_position(positional):
        return transform(value) if isinstance(value, str) else value
    if isinstance(value, Mapping):
        return _transform_mapping(positional, value, transform)
    if isinstance(value, list | tuple):
        return [
            _transform_secret_leaves(
                _element_annotation(positional, index), item, transform
            )
            for index, item in enumerate(value)
        ]
    return value


def _transform_mapping(
    positional: list[Any],
    value: Mapping[str, Any],
    transform: Callable[[str], str],
) -> Any:
    """Return ``value`` transformed as a secret-valued mapping or a model dump.

    :param positional: The candidate types for the mapping's JSON position.
    :param value: The stored mapping.
    :param transform: The leaf transformation to apply.
    :return: A new mapping, or ``value`` when the position resolves to neither.
    """
    mapping_value = _mapping_value_annotation(positional)
    if mapping_value is not None:
        return {
            name: _transform_secret_leaves(mapping_value, item, transform)
            for name, item in value.items()
        }
    models = _candidate_models(positional)
    if not models:
        return value
    return {
        name: _transform_secret_leaves(_field_annotation(models, name), item, transform)
        for name, item in value.items()
    }
