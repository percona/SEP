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

"""Define tests for the app.core.db.sql_types module."""

import random
from unittest.mock import MagicMock

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db.sql_types import (
    AutoJSON,
    MAYBE_COMPRESSED_TEXT_COMPRESSED_PREFIX,
    MAYBE_COMPRESSED_TEXT_RAW_PREFIX,
    MaybeCompressedText,
)


class TestAutoJSON:
    """Test the AutoJSON TypeDecorator."""

    def test_load_dialect_impl_postgresql(self):
        """Assert JSONB is used for the PostgreSQL dialect."""
        auto_json = AutoJSON()
        dialect = MagicMock()
        dialect.name = "postgresql"
        dialect.type_descriptor = lambda t: t

        result = auto_json.load_dialect_impl(dialect)

        assert isinstance(result, JSONB)

    def test_load_dialect_impl_sqlite(self):
        """Assert JSON is used for SQLite."""
        auto_json = AutoJSON()
        dialect = MagicMock()
        dialect.name = "sqlite"
        dialect.type_descriptor = lambda t: t

        result = auto_json.load_dialect_impl(dialect)

        assert isinstance(result, JSON)

    def test_cache_ok(self):
        """Assert cache_ok is set to True."""
        assert AutoJSON.cache_ok is True


class TestMaybeCompressedText:
    """Test the MaybeCompressedText TypeDecorator."""

    def _roundtrip(self, value):
        """Bind and unbind a value through MaybeCompressedText."""
        col = MaybeCompressedText()
        bound = col.process_bind_param(value, dialect=None)
        restored = col.process_result_value(bound, dialect=None)
        return bound, restored

    def test_none_roundtrip(self):
        """Assert None round-trips to None in both directions."""
        bound, restored = self._roundtrip(None)
        assert bound is None
        assert restored is None

    def test_empty_string(self):
        """Assert an empty string round-trips with a raw prefix."""
        bound, restored = self._roundtrip("")
        assert bound == MAYBE_COMPRESSED_TEXT_RAW_PREFIX
        assert restored == ""

    def test_short_ascii_stays_raw(self):
        """Assert short ASCII content is stored uncompressed."""
        value = "x" * 100
        bound, restored = self._roundtrip(value)
        assert bound.startswith(MAYBE_COMPRESSED_TEXT_RAW_PREFIX)
        assert restored == value

    def test_large_repetitive_text_is_compressed(self):
        """Assert compressible content is stored with the compressed prefix."""
        value = "hello world\n" * 1024
        bound, restored = self._roundtrip(value)
        assert bound.startswith(MAYBE_COMPRESSED_TEXT_COMPRESSED_PREFIX)
        assert len(bound) < len(value.encode("utf-8"))
        assert restored == value

    def test_small_high_entropy_text_stays_raw(self):
        """Assert short high-entropy content falls back to the raw prefix.

        Content just above the compression threshold has too little redundancy
        for zlib to overcome its framing overhead, so the writer must keep the
        original bytes instead of storing a larger compressed payload.
        """
        rng = random.Random(42)
        alphabet = "".join(chr(c) for c in range(33, 127))
        value = "".join(rng.choice(alphabet) for _ in range(260))
        bound, restored = self._roundtrip(value)
        assert bound.startswith(MAYBE_COMPRESSED_TEXT_RAW_PREFIX)
        assert restored == value

    def test_unicode_roundtrip(self):
        """Assert Unicode content survives the round-trip."""
        value = "héllo 🐳 日本 " * 200
        bound, restored = self._roundtrip(value)
        assert restored == value
        assert bound is not None

    def test_cache_ok(self):
        """Assert cache_ok is set to True."""
        assert MaybeCompressedText.cache_ok is True
