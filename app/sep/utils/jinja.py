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

"""Define Jinja2 filters and utilities."""

from typing import Any

from pygments import highlight
from pygments.formatters.html import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
from pygments.util import ClassNotFound


def syntax_highlight_css(cssclass: str = "highlight", **fmt_options: Any) -> str:
    """Generate CSS style definitions for syntax highlighting using Pygments.

    This function creates an instance of the Pygments HTML formatter with the
    specified CSS class and formatting options, then returns the CSS style
    definitions required for highlighting.

    :param cssclass: The CSS class name to be applied to highlighted code blocks.
        Defaults to "highlight".
    :type cssclass: str
    :param fmt_options: Additional keyword arguments passed to the
        :class:`pygments.formatters.HtmlFormatter`.
    :type fmt_options: Any
    :return: A string containing the CSS style definitions for syntax highlighting.
    :rtype: str
    """
    fmt_options["cssclass"] = cssclass
    formatter = HtmlFormatter(**fmt_options)
    return formatter.get_style_defs()


def syntax_highlight(code: str, language: str | None = None, **fmt_options: Any) -> str:
    """Apply syntax highlighting to the provided source code using Pygments.

    This function defines a jinja2 filter that applies syntax highlighting to a block
    of code using Pygments. If a specific language is provided, it will attempt to
    retrieve the corresponding lexer. If the lexer for the given language is not found,
    or if no language is specified, it will either guess the lexer based on the
    code content or default to a plain text lexer.

    :param code: The source code that is to be highlighted.
    :type code: str
    :param language: The programming language of the code. If not provided, the lexer is
        guessed.
    :type language: str or None
    :param fmt_options: Additional keyword arguments passed to the
        :class:`pygments.formatters.HtmlFormatter`.
    :type fmt_options: Any
    :return: A string containing HTML markup with syntax-highlighted code.
    :rtype: str
    """
    if language is None:
        lexer = guess_lexer(code, stripall=True)
    else:
        try:
            lexer = get_lexer_by_name(language, stripall=True)
        except ClassNotFound:
            lexer = TextLexer(stripall=True)
    return highlight(code, lexer, HtmlFormatter(**fmt_options))
