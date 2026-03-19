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

"""Define tests for the app.sep.utils.jinja module."""

import pytest
from faker import Faker
from pygments.lexers import TextLexer
from pygments.util import ClassNotFound

from app.sep.utils.jinja import syntax_highlight, syntax_highlight_css


@pytest.fixture
def random_json(faker: Faker) -> str:
    """Generate a random JSON string."""
    return faker.json()


def test_syntax_highlight_css_default_generates_dual_theme():
    """Test that syntax_highlight_css generates both light and dark theme CSS."""
    css = syntax_highlight_css()
    assert '[data-theme="light"] .highlight' in css
    assert '[data-theme="dark"] .highlight' in css


def test_syntax_highlight_css_custom_class():
    """Test that syntax_highlight_css uses the custom class in theme selectors."""
    css = syntax_highlight_css("my-code-block", linenos=True)
    assert '[data-theme="light"] .my-code-block' in css
    assert '[data-theme="dark"] .my-code-block' in css
    assert "linenos" in css


def test_syntax_highlight_css_custom_styles():
    """Test that syntax_highlight_css accepts custom light and dark style names."""
    css = syntax_highlight_css(light_style="friendly", dark_style="native")
    assert '[data-theme="light"] .highlight' in css
    assert '[data-theme="dark"] .highlight' in css


def test_syntax_highlight_guess_lexer(mocker, random_json):
    """Test that syntax_highlight calls guess_lexer when no language is provided."""
    guess_lexer_mock = mocker.patch(
        "app.sep.utils.jinja.guess_lexer", return_value=TextLexer()
    )
    syntax_highlight(random_json)
    guess_lexer_mock.assert_called_once_with(random_json, stripall=True)


def test_syntax_highlight_with_valid_language(mocker, random_json):
    """Test that syntax_highlight calls get_lexer_by_name for a valid language."""
    get_lexer_mock = mocker.patch(
        "app.sep.utils.jinja.get_lexer_by_name",
    )
    highlighted = syntax_highlight(random_json, language="python")
    get_lexer_mock.assert_called_once_with("python", stripall=True)
    assert "<div" in highlighted


def test_syntax_highlight_with_unknown_language(mocker, random_json):
    """Test that syntax_highlight falls back to TextLexer when an unknown language is used."""
    get_lexer_mock = mocker.patch(
        "app.sep.utils.jinja.get_lexer_by_name",
        side_effect=ClassNotFound("Unknown language"),
    )
    highlight_mock = mocker.patch("app.sep.utils.jinja.highlight")
    syntax_highlight(random_json, language="unknown_lang")
    get_lexer_mock.assert_called_once()
    highlight_mock.assert_called_once()
    assert isinstance(highlight_mock.call_args.args[1], TextLexer)
