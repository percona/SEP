# Copyright (C) 2025 Percona LLC
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

"""Define custom SQLAlchemy column types."""

import zlib
from typing import Any

from sqlalchemy import JSON, LargeBinary, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.sql.type_api import TypeEngine

MAYBE_COMPRESSED_TEXT_RAW_PREFIX = b"\x00"
MAYBE_COMPRESSED_TEXT_COMPRESSED_PREFIX = b"\x01"
MAYBE_COMPRESSED_TEXT_MIN_BYTES = 256
MAYBE_COMPRESSED_TEXT_MIN_SAVINGS_RATIO = 0.10


class AutoJSON(TypeDecorator):
    """Resolve to JSONB on PostgreSQL and JSON on other dialects.

    :cvar impl: The base implementation type.
    :vartype impl: type[JSON]
    :cvar cache_ok: Allow SQLAlchemy to cache compiled statements using this type.
    :vartype cache_ok: bool
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        """Return the dialect-specific type implementation.

        :param dialect: The SQLAlchemy dialect in use.
        :type dialect: Dialect
        :return: JSONB for PostgreSQL, JSON for all other dialects.
        :rtype: TypeEngine[Any]
        """
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return super().load_dialect_impl(dialect)


class MaybeCompressedText(TypeDecorator):
    """Store UTF-8 text as bytes, optionally zlib-compressed, with a 1-byte prefix.

    The prefix distinguishes raw and compressed payloads so each row can pick the
    smaller representation without needing a separate column. Compression is only
    applied when the raw payload is at least ``MAYBE_COMPRESSED_TEXT_MIN_BYTES`` and
    the compressed form saves at least ``MAYBE_COMPRESSED_TEXT_MIN_SAVINGS_RATIO``
    of the original size.

    :cvar impl: The underlying SQLAlchemy column type.
    :vartype impl: type[LargeBinary]
    :cvar cache_ok: Allow SQLAlchemy to cache compiled statements using this type.
    :vartype cache_ok: bool
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:  # noqa: ARG002
        """Serialize UTF-8 text into a prefixed byte string for storage.

        :param value: The text value to store.
        :type value: Any
        :param dialect: The SQLAlchemy dialect in use.
        :type dialect: Any
        :return: The prefixed bytes ready for the underlying ``LargeBinary`` column,
            or ``None`` when the input is ``None``.
        :rtype: Any
        """
        if value is None:
            return None
        encoded = value.encode("utf-8")
        if len(encoded) < MAYBE_COMPRESSED_TEXT_MIN_BYTES:
            return MAYBE_COMPRESSED_TEXT_RAW_PREFIX + encoded
        compressed = zlib.compress(encoded)
        if len(compressed) >= len(encoded) * (
            1 - MAYBE_COMPRESSED_TEXT_MIN_SAVINGS_RATIO
        ):
            return MAYBE_COMPRESSED_TEXT_RAW_PREFIX + encoded
        return MAYBE_COMPRESSED_TEXT_COMPRESSED_PREFIX + compressed

    def process_result_value(self, value: Any, dialect: Any) -> Any:  # noqa: ARG002
        """Deserialize a prefixed byte string back into UTF-8 text.

        :param value: The raw bytes from the database.
        :type value: Any
        :param dialect: The SQLAlchemy dialect in use.
        :type dialect: Any
        :return: The decoded UTF-8 text, or ``None`` when the input is ``None``.
        :rtype: Any
        """
        if value is None:
            return None
        prefix, payload = value[:1], value[1:]
        if prefix == MAYBE_COMPRESSED_TEXT_COMPRESSED_PREFIX:
            return zlib.decompress(payload).decode("utf-8")
        return payload.decode("utf-8")
