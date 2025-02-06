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


def test_syntax_highlight_css_default():
    """Test that syntax_highlight_css returns CSS definitions with the default class."""
    css = syntax_highlight_css()
    assert ".highlight" in css
    assert "color" in css


def test_syntax_highlight_css_custom_class():
    """Test that syntax_highlight_css can generate CSS for a custom class name."""
    custom_class = "my-code-block"
    css = syntax_highlight_css(custom_class, linenos=True)
    assert f".{custom_class}" in css
    assert "linenos" in css


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
