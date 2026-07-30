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

"""Define tests for the app.core.utils.cli_args kernel."""

import pytest

from app.core.utils.cli_args import (
    arg_template_identifiers,
    is_value_arg_template,
    render_value_arg,
)
from app.sep.apps.framework import spec
from app.sep.snippets.models import meta, snippet


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("--x=${value}", True),
        ("--flag", False),
        ("--$name ${value}", True),
        ("--$name", False),
    ],
    ids=["value-arg", "flag", "named-value-arg", "named-flag"],
)
def test_is_value_arg_template(template, expected):
    """Treat a template as a value arg only when it carries the ``${value}`` placeholder."""
    assert is_value_arg_template(template) is expected


def test_arg_template_identifiers():
    """Enumerate every ``$``-placeholder name the template declares."""
    assert arg_template_identifiers("--$name ${value}") == {"name", "value"}
    assert arg_template_identifiers("--flag") == set()


def test_render_value_arg_whitespace_stays_one_token():
    """Keep a whitespace-bearing value a single token through quote-then-split."""
    assert render_value_arg("--db=${value}", "a b") == ["--db=a b"]


def test_render_value_arg_custom_stringify():
    """Apply the injected ``stringify`` in place of the default ``str`` serializer."""
    assert render_value_arg("--db=${value}", "x", stringify=lambda _: "Z") == ["--db=Z"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a;b", ["--db=a;b"]),
        ("$X", ["--db=$X"]),
        ("`whoami`", ["--db=`whoami`"]),
    ],
    ids=["semicolon", "dollar", "backtick"],
)
def test_render_value_arg_shell_metachars_literalized(value, expected):
    """Preserve a shell-metachar value as a single literal token."""
    assert render_value_arg("--db=${value}", value) == expected


def test_render_value_arg_preserves_unknown_placeholder():
    """Keep an unknown placeholder intact while substituting ``${value}``."""
    assert render_value_arg("--$other=${value}", "x") == ["--$other=x"]


def test_kernel_consumers_import_without_cycle():
    """Verify both delegating surfaces import with the kernel without a cycle.

    The kernel lives in ``app.core``, which cannot import ``app.sep``, so wiring
    it between the framework run-command path and the snippet exec path cannot
    form a cycle. This module importing both consumers alongside the kernel
    guards that, and the identity assertions pin the delegation wiring.
    """
    assert spec.render_value_arg is render_value_arg
    assert spec.is_value_arg_template is is_value_arg_template
    assert spec.arg_template_identifiers is arg_template_identifiers
    assert meta.is_value_arg_template is is_value_arg_template
    assert snippet.render_value_arg is render_value_arg
