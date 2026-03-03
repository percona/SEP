# Copyright 2026 Percona LLC
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

from app.core.utils.strings import b64encode_str, slugify


def test_slugify():
    """Test slugify utility for various input cases."""
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("  Python@3.8  ") == "python-3-8"
    assert slugify("Café Münchén") == "cafe-munchen"
    assert slugify("___") == ""
    assert slugify("") == ""
    assert slugify("No_Special-Characters") == "no-special-characters"


def test_b64encode_str():
    """Test b64encode_str utility for base64 encoding strings."""
    assert b64encode_str("hello") == "aGVsbG8="
    assert b64encode_str("") == ""

    encoded = b64encode_str("café", encoding="latin-1")
    assert encoded == b64encode("café".encode("latin-1")).decode("latin-1")
