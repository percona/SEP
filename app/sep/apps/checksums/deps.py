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

"""Define dependencies for the Checksums plugin."""

import logging

from app.sep.apps.checksums.models import ChecksumsForm, OWNER
from app.sep.apps.checksums.spec import (
    build_checksums_spec,
    resolve_checksums_target_args,
)
from app.sep.apps.framework.form_dsl import (
    derive_arg_parser_from_model,
    make_arg_parser,
)
from app.sep.apps.framework.spec import (
    assemble_envelope,
    resolve_refs,
    stamp_form_input,
)
from app.sep.deps import InventoryAPI
from app.tasks.models import TaskWrite

logger = logging.getLogger(__name__)


async def build_checksums_payload(
    form: ChecksumsForm,
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build a checksums ``TaskWrite`` from the model-first create form.

    Resolve reference fields and multi-value schema/table targets, assemble the
    run-command spec, and stamp the validated form body under ``data['_form']``.

    :param form: The validated checksums create form.
    :param inventory_api: The inventory API client.
    :return: A fully constructed ``TaskWrite`` object.
    """
    resolved = await resolve_refs(form, inventory_api)
    databases_arg, tables_arg = await resolve_checksums_target_args(form, inventory_api)
    spec = build_checksums_spec(
        form,
        resolved,
        databases_arg=databases_arg,
        tables_arg=tables_arg,
    )
    write = assemble_envelope(
        spec,
        resolved,
        name=form.task_name,
        owner=OWNER,
        alert_on_fail=form.alert_on_fail,
    )
    stamp_form_input(write, form)
    return write


_CHECKSUMS_DEFAULTS = {
    "recursion_method": "processlist",
    "databases": "",
    "tables": "",
    "pause_file": "",
    "binary_index": False,
    "explain_arg": False,
    "fail_on_stopped_replication": False,
    "truncate_replicate_table": False,
    "progress": "",
    "set_vars": "",
    "max_load": "",
    "chunk_time": "",
    "max_lag": "",
    "defaults_file": "",
    "extra_args": "",
}

_CHECKSUMS_ARG_MAPPINGS, _CHECKSUMS_FLAG_MAPPINGS = derive_arg_parser_from_model(
    ChecksumsForm,
    extra_arg_mappings={
        "--recursion-method=": "recursion_method",
        "--databases=": "databases",
        "--tables=": "tables",
    },
)

parse_checksums_task_args = make_arg_parser(
    defaults=_CHECKSUMS_DEFAULTS,
    arg_mappings=_CHECKSUMS_ARG_MAPPINGS,
    flag_mappings=_CHECKSUMS_FLAG_MAPPINGS,
    skip_leading_positional=True,
)
