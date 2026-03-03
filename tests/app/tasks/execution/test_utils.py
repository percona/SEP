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

"""Define tests for the app.tasks.execution.utils module."""

from app.tasks.execution.utils import minify_file_content


def test_minify_valid_python_code():
    """Test minification of valid Python code."""
    python_code = """
def foo():
    x = 1
    y = 2
    return x + y
"""
    minified_code = minify_file_content(python_code, file_ext="py")
    assert minified_code.strip() != ""
    assert "\n" not in minified_code or len(minified_code.split("\n")) == 1
    assert "def" in minified_code
    assert "return" in minified_code


def test_minify_unrelated_file_extension():
    """Test minification with a non-Python file extension."""
    text_content = "This is some plain text."
    result = minify_file_content(text_content, file_ext="txt")
    assert result == text_content


def test_minify_with_syntax_error():
    """Test that syntax errors are handled gracefully."""
    broken_python_code = "def baz()\n    print('missing colon')"
    result = minify_file_content(broken_python_code, file_ext="py")
    assert result == broken_python_code
