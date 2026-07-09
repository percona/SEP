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

"""Define tests for the app.sep.apps.framework.form_dsl.pt_toolkit module."""

from app.sep.apps.framework.form_dsl.pt_toolkit import (
    DSN_TABLE_DEFAULT,
    make_arg_parser,
)

_DEFAULTS = {"alter": "", "flag": False, "extra_args": ""}
_ARG_MAPPINGS = {"--alter=": "alter"}
_FLAG_MAPPINGS = {"--flag": "flag"}


def _parser(**overrides):
    """Build a small parser with the shared mappings, applying keyword overrides."""
    kwargs = {
        "defaults": _DEFAULTS,
        "arg_mappings": _ARG_MAPPINGS,
        "flag_mappings": _FLAG_MAPPINGS,
    }
    kwargs.update(overrides)
    return make_arg_parser(**kwargs)


def test_dsn_table_default_value():
    """Expose the shared Percona-Toolkit DSN-table default."""
    assert DSN_TABLE_DEFAULT == "D=percona,t=dsns"


def test_value_arg_dispatch_takes_text_after_equals():
    """Map a ``--flag=value`` arg to its field using the text after the first ``=``."""
    assert _parser()({"args": "--alter=ADD_INDEX"})["alter"] == "ADD_INDEX"


def test_flag_arg_dispatch_sets_true():
    """Set a boolean field ``True`` when its bare flag token is present."""
    assert _parser()({"args": "--flag"})["flag"] is True


def test_empty_and_missing_args_return_pristine_defaults():
    """Return a copy of the defaults when ``args`` is missing or empty."""
    parse = _parser()
    assert parse({}) == _DEFAULTS
    assert parse({"args": ""}) == _DEFAULTS


def test_skip_leading_positional_drops_the_first_token():
    """Drop the first token unconditionally when ``skip_leading_positional`` is set."""
    parse = _parser(skip_leading_positional=True)
    assert parse({"args": "P=3306,D=db --flag"})["flag"] is True
    assert parse({"args": "--flag"})["flag"] is False


def test_drop_shaped_positionals_ignores_shaped_tokens():
    """Skip a non-``--`` token containing ``=`` without collecting it as an extra arg."""
    parse = _parser(drop_shaped_positionals=True, collect_extra_args=True)
    result = parse({"args": "P=3306,D=db --alter=ADD_INDEX"})
    assert result["alter"] == "ADD_INDEX"
    assert result["extra_args"] == ""


def test_collect_extra_args_accumulates_unknown_tokens():
    """Accumulate unrecognized tokens into ``extra_args`` when collecting is enabled."""
    result = _parser(collect_extra_args=True)(
        {"args": "--unknown-one --unknown-two=val"}
    )
    assert result["extra_args"] == "--unknown-one --unknown-two=val"


def test_reserved_flags_are_ignored_not_collected():
    """Drop a reserved flag without mapping it to a field or collecting it."""
    parse = _parser(collect_extra_args=True, reserved_flags=frozenset({"--execute"}))
    result = parse({"args": "--execute --other"})
    assert result["extra_args"] == "--other"


def test_unknown_args_dropped_when_not_collecting():
    """Drop unrecognized tokens when ``collect_extra_args`` is off."""
    assert _parser()({"args": "--unknown"}) == _DEFAULTS


def test_recursion_handler_consumes_its_arg_before_mappings():
    """Run a supplied recursion handler ahead of the value and flag mappings."""

    def handler(arg, values):
        if arg.startswith("--recursion-method="):
            values["recursion"] = arg.split("=", 1)[1]
            return True
        return False

    parse = make_arg_parser(
        defaults={"recursion": "", **_DEFAULTS},
        arg_mappings=_ARG_MAPPINGS,
        flag_mappings=_FLAG_MAPPINGS,
        recursion_handler=handler,
    )
    assert parse({"args": "--recursion-method=dsn"})["recursion"] == "dsn"


def test_no_state_leak_across_invocations():
    """Start every parse from pristine defaults so parses never leak into each other."""
    parse = _parser()
    populated = parse({"args": "--alter=CHANGED --flag"})
    assert populated["alter"] == "CHANGED"
    assert populated["flag"] is True

    pristine = parse({"args": ""})
    assert pristine == _DEFAULTS
    assert pristine["alter"] == ""
    assert pristine["flag"] is False
