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

"""Resolve ``${value}`` CLI-argument templates to shell tokens.

This is the single implementation the framework run-command path
(:func:`app.sep.apps.framework.spec.build_command_args`) and the snippet
exec-python-artifact path (:meth:`app.sep.snippets.models.snippet.BaseSnippetArgs.format_args`)
both delegate to for the shared ``${value}`` template convention and the
value-arg vs flag discrimination. Surface-specific concerns — truthy gating,
argument ordering, flag rendering, the ``${name}`` default-format placeholder,
and the per-surface value serializer — stay with each caller.
"""

import shlex
from collections.abc import Callable
from string import Template
from typing import Any

VALUE_PLACEHOLDER = "value"


def arg_template_identifiers(template: str) -> set[str]:
    """Return the ``$``-placeholder names in ``template``.

    :param template: The CLI-argument template.
    :return: The set of placeholder names the template declares.
    """
    return set(Template(template).get_identifiers())


def is_value_arg_template(template: str) -> bool:
    """Return whether ``template`` is a value arg rather than a flag.

    A value arg carries the ``${value}`` placeholder; a flag does not.

    :param template: The CLI-argument template.
    :return: ``True`` when ``template`` carries ``${value}``.
    """
    return VALUE_PLACEHOLDER in arg_template_identifiers(template)


def render_value_arg(
    template: str, value: Any, *, stringify: Callable[[Any], str] = str
) -> list[str]:
    """Resolve a CLI-argument template to CLI tokens, substituting ``${value}`` when present.

    The value is stringified (``stringify`` defaults to ``str``; callers inject
    their own serializer), ``shlex.quote``'d, substituted for ``${value}`` via
    ``safe_substitute`` (leaving any other placeholder intact), and
    ``shlex.split``. The quote → substitute → split round-trip keeps a
    whitespace-bearing value a single token.

    :param template: The CLI-argument template; ``${value}`` is substituted when
        present (a flag template without it passes through unchanged).
    :param value: The value substituted for ``${value}``.
    :param stringify: The serializer applied to ``value`` before quoting.
    :return: The resolved CLI tokens.
    """
    substituted = Template(template).safe_substitute(
        **{VALUE_PLACEHOLDER: shlex.quote(stringify(value))}
    )
    return shlex.split(substituted)
