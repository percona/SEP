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

"""Define tests for the app.core.utils.strings module."""

from base64 import b64encode

import pytest

from app.core.utils.strings import b64encode_str, join_or, slugify


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Hello, World!", "hello-world"),
        ("  Python@3.8  ", "python-3-8"),
        ("Café Münchén", "cafe-munchen"),
        ("___", ""),
        ("", ""),
        ("No_Special-Characters", "no-special-characters"),
    ],
    ids=[
        "hello-world",
        "strip-and-symbols",
        "unicode-accents",
        "only-underscores",
        "empty",
        "mixed-separators",
    ],
)
def test_slugify(value, expected):
    """Test slugify utility for various input cases."""
    assert slugify(value) == expected


def test_b64encode_str():
    """Test b64encode_str utility for base64 encoding strings."""
    assert b64encode_str("hello") == "aGVsbG8="
    assert b64encode_str("") == ""

    encoded = b64encode_str("café", encoding="latin-1")
    assert encoded == b64encode("café".encode("latin-1")).decode("latin-1")


class TestJoinOr:
    """Read a list of alternatives back as English prose."""

    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            (["quicklz"], "quicklz"),
            (["lz4", "quicklz"], "lz4 or quicklz"),
            (["zstd", "lz4", "quicklz"], "zstd, lz4 or quicklz"),
        ],
        ids=["single", "pair", "three"],
    )
    def test_joins_alternatives(self, values, expected):
        """Join the alternatives with commas and a trailing ``or``."""
        assert join_or(values) == expected

    def test_preserves_the_given_order(self):
        """Leave the caller's ordering alone, since it carries meaning."""
        assert join_or(["quicklz", "zstd", "lz4"]) == "quicklz, zstd or lz4"

    def test_accepts_any_sequence(self):
        """Take a tuple as readily as a list, as the matrix rows are tuples."""
        assert join_or(("lz4", "quicklz")) == "lz4 or quicklz"
