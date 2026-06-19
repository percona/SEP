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

"""Build the ``pt-table-checksum`` run-command spec for the Checksums app.

:func:`build_checksums_args` is the single source of the CLI argument string
(DSN construction, ``--recursion-method=dsn=…`` expansion, optional/flag arg
mapping); both the model-first JSON path (via :func:`build_checksums_spec` fed to
the framework's three-phase create) and the legacy Jinja form path (via
``deps._assemble_checksum_payload``) delegate to it, so a checksum task's Nomad
payload is byte-identical regardless of the call origin. The framework's
``assemble_envelope`` supplies the executor ``target``, ``_service_name``, and
the connectivity meta keys, byte-uniform with the canonical hand-written
envelope.
"""

import shlex
from collections.abc import Iterable

from app.sep.inventory import CreatedService
from app.sep.plugins.checksums.models import ChecksumsForm
from app.sep.plugins.framework.payload import ResolvedEntities, RunCommandSpec

DEFAULT_RECURSION_DSN_TABLE = "D=percona,t=dsns"


def build_checksums_args(
    service: CreatedService,
    *,
    recursion_method: str,
    dsn_table: str,
    databases: str,
    tables: str,
    pause_file: str,
    binary_index: bool,
    explain_arg: bool,
    fail_on_stopped_replication: bool,
    truncate_replicate_table: bool,
    progress: str,
    set_vars: str,
    max_load: str,
    chunk_time: str,
    max_lag: str,
    extra_remaining_args: Iterable[str] = (),
) -> list[str]:
    """Build the ordered ``pt-table-checksum`` CLI argument list.

    Own DSN construction, ``--recursion-method=dsn=…`` expansion (on a local copy
    — never mutates caller arguments), and the optional/flag arg mapping. The
    returned list is ``shlex.join``'d by the caller into ``meta.args``.

    :param service: The resolved inventory service (drives the DSN host/port).
    :param recursion_method: The replica-discovery method (e.g. ``"processlist"``).
    :param dsn_table: DSN table used when ``recursion_method == "dsn"``.
    :param databases: Comma-separated database names (pre-resolved).
    :param tables: Comma-separated ``schema.table`` strings (pre-resolved).
    :param pause_file: Pause-file path.
    :param binary_index: Enable ``--binary-index``.
    :param explain_arg: Enable ``--explain``.
    :param fail_on_stopped_replication: Enable ``--fail-on-stopped-replication``.
    :param truncate_replicate_table: Enable ``--truncate-replicate-table``.
    :param progress: ``--progress`` value.
    :param set_vars: ``--set-vars`` value.
    :param max_load: ``--max-load`` value.
    :param chunk_time: ``--chunk-time`` value.
    :param max_lag: ``--max-lag`` value.
    :param extra_remaining_args: Additional pre-parsed CLI args (form path only).
    :return: The ordered argument list (DSN first), ready for ``shlex.join``.
    """
    dsn = ""
    if service.port is not None:
        dsn = f"P={service.port},{dsn}"
    if service.node.address != "localhost":
        dsn = f"h={service.node.address},{dsn}"

    effective_recursion_method = recursion_method
    if recursion_method == "dsn":
        stripped_dsn = dsn.rstrip(",")
        dsn_table_part = (dsn_table or "").strip() or DEFAULT_RECURSION_DSN_TABLE
        effective_recursion_method = f"dsn={stripped_dsn},{dsn_table_part}"

    args = [dsn]

    if effective_recursion_method:
        args.append(f"--recursion-method={effective_recursion_method}")

    args.extend(extra_remaining_args)

    optional_args = {
        "databases": f"--databases={databases}",
        "tables": f"--tables={tables}",
        "pause_file": f"--pause-file={pause_file}",
        "set_vars": f"--set-vars={set_vars}",
        "max_load": f"--max-load={max_load}",
        "chunk_time": f"--chunk-time={chunk_time}",
        "max_lag": f"--max-lag={max_lag}",
        "progress": f"--progress={progress}",
    }
    local_values = {
        "databases": databases,
        "tables": tables,
        "pause_file": pause_file,
        "set_vars": set_vars,
        "max_load": max_load,
        "chunk_time": chunk_time,
        "max_lag": max_lag,
        "progress": progress,
    }
    args.extend(arg for key, arg in optional_args.items() if local_values[key])

    flag_args = {
        "binary_index": "--binary-index",
        "explain_arg": "--explain",
        "fail_on_stopped_replication": "--fail-on-stopped-replication",
        "truncate_replicate_table": "--truncate-replicate-table",
    }
    flag_values = {
        "binary_index": binary_index,
        "explain_arg": explain_arg,
        "fail_on_stopped_replication": fail_on_stopped_replication,
        "truncate_replicate_table": truncate_replicate_table,
    }
    args.extend(arg for key, arg in flag_args.items() if flag_values[key])

    return args


def build_checksums_spec(
    form: ChecksumsForm, resolved: ResolvedEntities
) -> RunCommandSpec:
    """Build the ``pt-table-checksum`` run-command spec from the validated form.

    The framework's ``assemble_envelope`` fills ``target`` (the executor
    ``HostRef``), ``_service_name``, and the connectivity keys around this spec;
    here we own only the command, the ``shlex.join``'d args, and the
    ``_service_host`` / ``_service_port`` extras.

    :param form: The validated create form (a ``ChecksumsForm``).
    :param resolved: The entities resolved from the form's reference fields; its
        ``service`` is the ``ServiceRef`` selection (always present — the field is
        required).
    :return: The run-command spec consumed by ``assemble_envelope``.
    """
    service = resolved.service
    args = build_checksums_args(
        service,
        recursion_method=form.recursion_method,
        dsn_table=form.dsn_table,
        databases=form.databases,
        tables=form.tables,
        pause_file=form.pause_file,
        binary_index=form.binary_index,
        explain_arg=form.explain_arg,
        fail_on_stopped_replication=form.fail_on_stopped_replication,
        truncate_replicate_table=form.truncate_replicate_table,
        progress=form.progress,
        set_vars=form.set_vars,
        max_load=form.max_load,
        chunk_time=form.chunk_time,
        max_lag=form.max_lag,
    )
    return RunCommandSpec(
        command="pt-table-checksum",
        args=shlex.join(args),
        extra_meta={
            "_service_host": service.node.address,
            "_service_port": service.port,
        },
    )
