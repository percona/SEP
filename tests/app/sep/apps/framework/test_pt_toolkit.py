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

from typing import Annotated

from pydantic import BaseModel

from app.sep.apps.alters.models import AltersCreate
from app.sep.apps.checksums.models import ChecksumsForm
from app.sep.apps.framework.form_dsl.markers import ArgFormat
from app.sep.apps.framework.form_dsl.pt_toolkit import (
    derive_arg_parser_from_model,
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


class _DeriveSampleForm(BaseModel):
    """Provide a minimal model exercising each ``derive_arg_parser_from_model`` branch."""

    val_field: Annotated[str, ArgFormat()] = ""
    bool_field: Annotated[bool, ArgFormat()] = False
    renamed_flag: Annotated[bool, ArgFormat("--explain")] = False
    plain_field: str = ""


def test_derive_templateless_value_maps_kebab_prefix():
    """Map a templateless non-bool field to a ``--<kebab>=`` value-arg prefix."""
    arg_mappings, _ = derive_arg_parser_from_model(_DeriveSampleForm)
    assert arg_mappings == {"--val-field=": "val_field"}


def test_derive_templateless_bool_maps_kebab_flag():
    """Map a templateless bool field to a ``--<kebab>`` flag token."""
    _, flag_mappings = derive_arg_parser_from_model(_DeriveSampleForm)
    assert flag_mappings["--bool-field"] == "bool_field"


def test_derive_explicit_flag_template_uses_given_token():
    """Map an explicit flag template to its own token, not the kebab field name."""
    _, flag_mappings = derive_arg_parser_from_model(_DeriveSampleForm)
    assert flag_mappings["--explain"] == "renamed_flag"
    assert "--renamed-flag" not in flag_mappings


def test_derive_skips_non_argformat_fields():
    """Filter out a field that carries no ``ArgFormat`` marker."""
    arg_mappings, flag_mappings = derive_arg_parser_from_model(_DeriveSampleForm)
    assert "plain_field" not in arg_mappings.values()
    assert "plain_field" not in flag_mappings.values()


def test_derive_merges_extra_mappings():
    """Merge extra mappings into the derived value and flag dicts."""
    arg_mappings, flag_mappings = derive_arg_parser_from_model(
        _DeriveSampleForm,
        extra_arg_mappings={"--alter=": "alter"},
        extra_flag_mappings={"--dry-run": "dry_run"},
    )
    assert arg_mappings["--alter="] == "alter"
    assert flag_mappings["--dry-run"] == "dry_run"


# Frozen copies of the origin/main hand-maintained reverse-parser mappings this
# ticket deletes. The production dicts are gone, so these local literals are the
# exactness oracle: the derived mappings must reproduce them byte-for-byte.
_EXPECTED_ALTERS_ARG_MAPPINGS = {
    "--alter=": "alter",
    "--pause-file=": "pause_file",
    "--new-table-name=": "new_table_name",
    "--tries=": "tries",
    "--set-vars=": "set_vars",
    "--critical-load=": "critical_load",
    "--max-load=": "max_load",
    "--chunk-time=": "chunk_time",
    "--max-lag=": "max_lag",
    "--max-flow-ctl=": "max_flow_ctl",
    "--progress=": "progress",
}
_EXPECTED_ALTERS_FLAG_MAPPINGS = {
    "--print": "print_arg",
    "--no-swap-tables": "no_swap_tables",
    "--no-drop-old-table": "no_drop_old_table",
    "--no-drop-new-table": "no_drop_new_table",
    "--no-drop-triggers": "no_drop_triggers",
}
_EXPECTED_CHECKSUMS_ARG_MAPPINGS = {
    "--recursion-method=": "recursion_method",
    "--databases=": "databases",
    "--tables=": "tables",
    "--pause-file=": "pause_file",
    "--set-vars=": "set_vars",
    "--max-load=": "max_load",
    "--chunk-time=": "chunk_time",
    "--max-lag=": "max_lag",
    "--progress=": "progress",
}
_EXPECTED_CHECKSUMS_FLAG_MAPPINGS = {
    "--binary-index": "binary_index",
    "--explain": "explain_arg",
    "--fail-on-stopped-replication": "fail_on_stopped_replication",
    "--truncate-replicate-table": "truncate_replicate_table",
}


def test_derive_reproduces_frozen_alters_mappings():
    """Build the same alters mappings the deleted hand-maintained dicts held."""
    arg_mappings, flag_mappings = derive_arg_parser_from_model(
        AltersCreate,
        extra_arg_mappings={"--alter=": "alter", "--progress=": "progress"},
    )
    assert arg_mappings == _EXPECTED_ALTERS_ARG_MAPPINGS
    assert flag_mappings == _EXPECTED_ALTERS_FLAG_MAPPINGS


def test_derive_reproduces_frozen_checksums_mappings():
    """Build the same checksums mappings the deleted hand-maintained dicts held."""
    arg_mappings, flag_mappings = derive_arg_parser_from_model(
        ChecksumsForm,
        extra_arg_mappings={
            "--recursion-method=": "recursion_method",
            "--databases=": "databases",
            "--tables=": "tables",
        },
    )
    assert arg_mappings == _EXPECTED_CHECKSUMS_ARG_MAPPINGS
    assert flag_mappings == _EXPECTED_CHECKSUMS_FLAG_MAPPINGS
