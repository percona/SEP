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

"""Define Jinja2 filters and utilities."""

from datetime import datetime
from typing import Any

from pygments import highlight
from pygments.formatters.html import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer, TextLexer
from pygments.util import ClassNotFound

from app.core.utils import make_datetime_utc


def syntax_highlight_css(
    cssclass: str = "highlight",
    *,
    light_style: str = "sas",
    dark_style: str = "monokai",
    **fmt_options: Any,
) -> str:
    """Generate dual-theme CSS for syntax highlighting using Pygments.

    Produce CSS rules scoped to ``[data-theme="light"]`` and
    ``[data-theme="dark"]`` selectors so that code blocks render correctly
    in both light and dark UI themes.

    :param cssclass: The CSS class name applied to highlighted code blocks.
    :type cssclass: str
    :param light_style: Pygments style name for the light theme.
    :type light_style: str
    :param dark_style: Pygments style name for the dark theme.
    :type dark_style: str
    :param fmt_options: Additional keyword arguments forwarded to
        :class:`pygments.formatters.HtmlFormatter`.
    :type fmt_options: Any
    :return: CSS style definitions containing both light-theme and dark-theme rules.
    :rtype: str
    """
    light_formatter = HtmlFormatter(style=light_style, cssclass=cssclass, **fmt_options)
    dark_formatter = HtmlFormatter(style=dark_style, cssclass=cssclass, **fmt_options)

    light_prefix = f'[data-theme="light"] .{cssclass}'
    dark_prefix = f'[data-theme="dark"] .{cssclass}'

    light_css = light_formatter.get_style_defs(light_prefix)
    dark_css = dark_formatter.get_style_defs(dark_prefix)

    return f"{light_css}\n{dark_css}"


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


def utc_isoformat(dt: datetime) -> str:
    """Convert a datetime to UTC and return a corresponding ISO 8601 formatted string.

    :param dt: Datetime to convert timezone.
    :type dt: datetime
    :return: ISO 8601 formatted string for aware datetime with timezone set to UTC.
    :rtype: str
    """
    return make_datetime_utc(dt).isoformat()


def humanize_bytes(num_bytes: int) -> str:
    """Return a humanized file size string from a number of bytes.

    :param num_bytes: Total number of bytes to humanize.
    :type num_bytes: int
    :return: Humanized file size.
    :rtype: str
    """
    bytes_treshold = 1024
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num_bytes) < bytes_treshold:
            return f"{num_bytes:3.1f}{unit}B"
        num_bytes /= bytes_treshold
    return f"{num_bytes:.1f}YiB"


DEFAULT_FILTERS = {
    "syntax_highlight": syntax_highlight,
    "utc_isoformat": utc_isoformat,
    "humanize_bytes": humanize_bytes,
}
