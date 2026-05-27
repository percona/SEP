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

"""Reference unit test for the Testing Trophy Unit layer.

Demonstrates the canonical pattern for unit tests in SEP:

- Tests a pure function in ``app/`` with no I/O, no fixtures beyond
  ``pytest``, and no test client.
- Uses ``@pytest.mark.parametrize`` for tabular coverage of the input space.
- Reads cleanly end-to-end — a reviewer can predict the assertion from the
  inputs without running the code.

The ``unit`` marker is applied automatically by ``tests/unit/conftest.py``;
no decoration on this file is required for ``pytest -m unit`` to pick it up.

"""

import pytest

from app.core.utils.strings import shorten_text, slugify


class TestSlugify:
    """Exercise :func:`app.core.utils.strings.slugify`."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Hello World", "hello-world"),
            ("  spaces  around  ", "spaces-around"),
            ("Snake_Case_Name", "snake-case-name"),
            ("Café résumé", "cafe-resume"),
            ("MiXeD/CASE!!separators", "mixed-case-separators"),
            ("", ""),
        ],
    )
    def test_produces_url_safe_slug(self, text: str, expected: str) -> None:
        """A range of inputs collapses to a lowercase, hyphen-separated slug."""
        assert slugify(text) == expected


class TestShortenText:
    """Exercise :func:`app.core.utils.strings.shorten_text`."""

    def test_short_input_is_returned_unchanged(self) -> None:
        """Text that already fits the limit is not modified."""
        assert shorten_text("short", max_length=100) == "short"

    def test_long_input_is_truncated_with_ellipsis(self) -> None:
        """Text longer than ``max_length`` gets the ellipsis suffix."""
        max_length = 20
        result = shorten_text("a" * 200, max_length=max_length)

        assert result.endswith("...")
        assert len(result) == max_length

    def test_keep_last_chars_preserves_tail(self) -> None:
        """``keep_last_chars`` preserves the original suffix after truncation."""
        result = shorten_text("a" * 100 + "TAIL", max_length=20, keep_last_chars=4)

        assert result.startswith("a")
        assert result.endswith("...TAIL")

    def test_rejects_inconsistent_lengths(self) -> None:
        """``max_length`` smaller than ``ellipsis`` + ``keep_last_chars`` is invalid."""
        with pytest.raises(ValueError, match="must be less than max_length"):
            shorten_text("a" * 200, max_length=5, keep_last_chars=10)
