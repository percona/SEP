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

"""Validate and resolve RFC 6901 JSON Pointers against decoded JSON documents.

A pointer is either the empty string (the whole document) or a sequence of
``/``-prefixed reference tokens, where ``~1`` encodes a literal ``/`` and ``~0``
a literal ``~``. Resolution errors name the offending token and its position and
never embed the document, which may carry data the caller must not log.
"""

__all__ = [
    "JsonPointerResolutionError",
    "parse_json_pointer",
    "resolve_json_pointer",
    "validate_json_pointer",
]

import re
from collections.abc import Mapping, Sequence
from typing import Any

#: Reference tokens addressing a sequence element, per RFC 6901 section 4.
_ARRAY_INDEX_PATTERN = re.compile(r"0|[1-9][0-9]*")

#: The escape characters a ``~`` may legally introduce.
_ESCAPE_CHARACTERS = frozenset({"0", "1"})


class JsonPointerResolutionError(LookupError):
    """Signal that a JSON Pointer does not address a value in the document."""


def validate_json_pointer(pointer: str) -> str:
    """Check ``pointer`` for RFC 6901 syntax and return it unchanged.

    :param pointer: The candidate pointer; ``""`` is the valid root pointer.
    :return: ``pointer`` unchanged.
    :raises ValueError: When a non-empty pointer does not start with ``/``, or
        carries a ``~`` that is not part of a ``~0`` / ``~1`` escape.
    """
    if not pointer:
        return pointer
    if not pointer.startswith("/"):
        raise ValueError(
            f"JSON Pointer {pointer!r} must start with '/' or be the empty "
            f"root pointer."
        )
    position = pointer.find("~")
    while position != -1:
        if pointer[position + 1 : position + 2] not in _ESCAPE_CHARACTERS:
            raise ValueError(
                f"JSON Pointer {pointer!r} has a '~' at index {position} that "
                f"is not part of a '~0' or '~1' escape."
            )
        position = pointer.find("~", position + 2)
    return pointer


def parse_json_pointer(pointer: str) -> tuple[str, ...]:
    """Split ``pointer`` into its decoded reference tokens.

    :param pointer: The pointer to tokenize; ``""`` yields no tokens.
    :return: The reference tokens with ``~1`` and ``~0`` escapes decoded.
    :raises ValueError: When ``pointer`` is not valid RFC 6901 syntax.
    """
    validate_json_pointer(pointer)
    if not pointer:
        return ()
    return tuple(
        token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")
    )


def _resolve_token(document: Any, token: str, position: int) -> Any:
    """Resolve a single reference token against the value it addresses.

    :param document: The value reached so far while walking the pointer.
    :param token: The decoded reference token to apply.
    :param position: The token's zero-based position, named in error messages.
    :return: The addressed value.
    :raises JsonPointerResolutionError: When ``document`` has no such member, or
        is neither a mapping nor a non-string sequence.
    """
    if isinstance(document, Mapping):
        if token not in document:
            raise JsonPointerResolutionError(
                f"No member {token!r} at pointer position {position}."
            )
        return document[token]
    if isinstance(document, Sequence) and not isinstance(document, str | bytes):
        if not _ARRAY_INDEX_PATTERN.fullmatch(token):
            raise JsonPointerResolutionError(
                f"Token {token!r} at pointer position {position} is not a "
                f"sequence index."
            )
        index = int(token)
        if index >= len(document):
            raise JsonPointerResolutionError(
                f"Sequence index {token!r} at pointer position {position} is "
                f"out of range."
            )
        return document[index]
    raise JsonPointerResolutionError(
        f"Cannot traverse token {token!r} at pointer position {position}: the "
        f"addressed value is a {type(document).__name__}."
    )


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Return the value ``pointer`` addresses within ``document``.

    :param document: The decoded JSON document to walk.
    :param pointer: The pointer to resolve; ``""`` returns ``document`` itself.
    :return: The addressed value.
    :raises ValueError: When ``pointer`` is not valid RFC 6901 syntax.
    :raises JsonPointerResolutionError: When a token does not address a value.
    """
    current = document
    for position, token in enumerate(parse_json_pointer(pointer)):
        current = _resolve_token(current, token, position)
    return current
