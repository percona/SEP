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

"""Provide the shared Percona-Toolkit reverse argument parser and DSN default.

The forward kernel (``build_command_args`` in ``framework/spec.py``) turns form
values into a stored task's CLI ``args`` string. This module holds the
reverse-direction counterpart shared by the ``alters``
(``pt-online-schema-change``) and ``checksums`` (``pt-table-checksum``) apps:
``make_arg_parser`` rebuilds a form-value dict from a stored task's ``args``
string, ``derive_arg_parser_from_model`` derives that parser's value/flag
mappings from the model's ``ArgFormat`` markers (the same markers the forward
kernel reads, so the two directions cannot desync), and ``DSN_TABLE_DEFAULT``
is the single ``D=percona,t=dsns`` DSN-table default both apps fall back to.
"""

import shlex
from collections.abc import Callable, Mapping
from string import Template
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from app.core.utils.cli_args import is_value_arg_template
from app.sep.apps.framework.form_dsl.markers import (
    find_arg_format,
    resolve_arg_template,
)

DSN_TABLE_DEFAULT = "D=percona,t=dsns"


def _apply_arg(
    arg: str,
    form_values: dict[str, Any],
    arg_mappings: Mapping[str, str],
    flag_mappings: Mapping[str, str],
) -> bool:
    """Apply a value-arg or bare-flag mapping to ``form_values`` in place.

    :param arg: The CLI token to match.
    :param form_values: The in-progress form-value dict, updated in place.
    :param arg_mappings: ``--flag=`` prefix to field name for value-carrying args.
    :param flag_mappings: Exact ``--flag`` token to boolean field name.
    :return: ``True`` when ``arg`` matched a value or flag mapping, ``False``
        otherwise.
    """
    value_field = next(
        (field for prefix, field in arg_mappings.items() if arg.startswith(prefix)),
        None,
    )
    if value_field is not None:
        form_values[value_field] = arg.split("=", 1)[1]
        return True

    flag_field = flag_mappings.get(arg)
    if flag_field is not None:
        form_values[flag_field] = True
        return True

    return False


def make_arg_parser(
    *,
    defaults: Mapping[str, Any],
    arg_mappings: Mapping[str, str],
    flag_mappings: Mapping[str, str],
    recursion_handler: Callable[[str, dict[str, Any]], bool] | None = None,
    skip_leading_positional: bool = False,
    drop_shaped_positionals: bool = False,
    collect_extra_args: bool = False,
    reserved_flags: frozenset[str] = frozenset(),
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Return a ``parse(meta) -> form_values`` reverse parser bound to one app's rules.

    The returned parser seeds a fresh dict from ``defaults``, splits
    ``meta["args"]`` with :func:`shlex.split`, and dispatches each token in
    order: an optional ``recursion_handler``, then ``arg_mappings``
    (``--flag=value`` prefixes), then ``flag_mappings`` (bare boolean flags). A
    token matching none of those is appended to ``extra_args`` only when
    ``collect_extra_args`` is set and it is not a reserved flag, otherwise it is
    dropped.

    :param defaults: Field-name to default-value mapping; copied fresh on every
        parse call so parses never leak state into one another.
    :param arg_mappings: ``--flag=`` prefix to field name for value-carrying
        args; the substring after the first ``=`` becomes the field value.
    :param flag_mappings: Exact ``--flag`` token to boolean field name; a present
        flag sets the field ``True``.
    :param recursion_handler: Optional app-specific callback consuming the
        ``--recursion-method=`` token; returns ``True`` when it handled the token
        (so no further dispatch runs for it), ``False`` otherwise.
    :param skip_leading_positional: Drop the first token before dispatch (the
        positional DSN that ``pt-table-checksum`` takes).
    :param drop_shaped_positionals: Skip any non-``--`` token containing ``=`` (a
        shaped positional such as ``P=3306,D=db,t=tbl``).
    :param collect_extra_args: Accumulate unrecognized tokens into the
        ``extra_args`` field (``shlex``-joined); when ``False`` they are dropped.
    :param reserved_flags: Flags recognized but intentionally ignored — never
        mapped to a field and never collected into ``extra_args``.
    :return: A parser taking a task ``meta`` dict and returning the form-value
        dict.
    """

    def parse_task_args(meta: dict[str, Any]) -> dict[str, Any]:
        """Parse a stored task's ``args`` string back into form field values.

        :param meta: The task meta carrying the ``args`` CLI string.
        :return: The reconstructed form-value dict.
        """
        form_values = dict(defaults)

        args_string = meta.get("args", "")
        if not args_string:
            return form_values

        args = shlex.split(args_string)
        if skip_leading_positional:
            args = args[1:]

        extra_args = []
        for arg in args:
            if drop_shaped_positionals and not arg.startswith("--") and "=" in arg:
                continue
            if recursion_handler is not None and recursion_handler(arg, form_values):
                continue
            if _apply_arg(arg, form_values, arg_mappings, flag_mappings):
                continue
            if collect_extra_args and arg not in reserved_flags:
                extra_args.append(arg)

        if collect_extra_args and extra_args:
            form_values["extra_args"] = shlex.join(extra_args)

        return form_values

    return parse_task_args


def derive_arg_parser_from_model(
    model: type[BaseModel],
    *,
    extra_arg_mappings: Mapping[str, str] = MappingProxyType({}),
    extra_flag_mappings: Mapping[str, str] = MappingProxyType({}),
) -> tuple[dict[str, str], dict[str, str]]:
    """Derive a reverse parser's ``arg_mappings`` / ``flag_mappings`` from a model.

    Walk ``model``'s fields in declaration order; for each field carrying an
    :class:`~app.sep.apps.framework.form_dsl.markers.ArgFormat` marker, resolve its
    template via the same resolver the forward ``build_command_args`` uses and
    classify it: a value-arg template (``--flag=${value}``) contributes its
    ``--flag=`` prefix to ``arg_mappings``, and a flag template (``--flag``)
    contributes its whole token to ``flag_mappings`` — both keyed to the field
    name. Sharing that resolver makes the ``ArgFormat`` markers the single source
    of truth for both the forward and reverse directions, so a kebab-spelling
    change can never desync them. The ``extra_*`` mappings supply the reverse
    entries for args an app renders outside its ``ArgFormat`` fields (a prefix
    positional, a multi-value ref rendered from resolved entities); they are
    merged last, so an explicit extra overrides a derived entry of the same key.

    :param model: The create model whose ``ArgFormat``-marked fields drive the
        derived mappings.
    :param extra_arg_mappings: Additional ``--flag=`` prefix to field-name value-arg
        entries for non-``ArgFormat`` args (merged last). Defaults to empty.
    :param extra_flag_mappings: Additional ``--flag`` token to field-name flag
        entries for non-``ArgFormat`` flags (merged last). Defaults to empty.
    :return: The ``(arg_mappings, flag_mappings)`` pair for :func:`make_arg_parser`.
    """
    arg_mappings = {}
    flag_mappings = {}
    for name, field_info in model.model_fields.items():
        marker = find_arg_format(name, field_info.metadata)
        if marker is None:
            continue
        template = resolve_arg_template(name, field_info.annotation, marker)
        if is_value_arg_template(template):
            arg_mappings[Template(template).safe_substitute(value="")] = name
        else:
            flag_mappings[template] = name
    arg_mappings.update(extra_arg_mappings)
    flag_mappings.update(extra_flag_mappings)
    return arg_mappings, flag_mappings
