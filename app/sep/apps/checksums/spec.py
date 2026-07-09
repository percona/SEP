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

:func:`build_checksums_arg_prefix` builds the entity-derived argument prefix (DSN
construction and ``--recursion-method=dsn=…`` expansion) shared by the model-first
JSON path (:func:`build_checksums_spec` fed to the framework's three-phase create)
and the legacy Jinja form path (``deps.assemble_checksum_payload``); the
declarative value/flag args come from the framework's
:func:`~app.sep.apps.framework.spec.build_command_args` driven by the form's
``ArgFormat`` markers, so a checksum task's Nomad payload is byte-identical
regardless of the call origin. The framework's ``assemble_envelope`` supplies the
executor ``target``, ``_service_name``, and the connectivity meta keys,
byte-uniform with the canonical hand-written envelope.
"""

import shlex
from collections.abc import Iterable

from app.sep.apps.checksums.models import ChecksumsForm
from app.sep.apps.framework.form_dsl import DSN_TABLE_DEFAULT
from app.sep.apps.framework.spec import (
    build_command_args,
    ResolvedEntities,
    RunCommandSpec,
)
from app.sep.inventory import CreatedService


def build_checksums_arg_prefix(
    service: CreatedService,
    *,
    recursion_method: str,
    dsn_table: str,
    extra_remaining_args: Iterable[str] = (),
) -> list[str]:
    """Return the entity-derived ``pt-table-checksum`` argument prefix.

    Build the leading ``[dsn]`` token (an empty string — rendered by ``shlex.join``
    as ``''`` — when the service is local and portless), the
    ``--recursion-method=...`` arg with ``dsn=...`` expanded when the method is
    ``dsn`` (on a local copy, never mutating caller arguments), and any pre-parsed
    extra args the legacy form path threads through. The declarative value/flag
    args follow via
    :func:`~app.sep.apps.framework.spec.build_command_args`.

    :param service: The resolved inventory service (drives the DSN host/port).
    :param recursion_method: The replica-discovery method (e.g. ``"processlist"``).
    :param dsn_table: DSN table used when ``recursion_method == "dsn"``; falls back
        to ``D=percona,t=dsns`` when blank.
    :param extra_remaining_args: Additional pre-parsed CLI args (legacy form path
        only; the model-first path passes none).
    :return: The ordered argument prefix, ready to precede the declarative args.
    """
    dsn = ""
    if service.port is not None:
        dsn = f"P={service.port},{dsn}"
    if service.node.address != "localhost":
        dsn = f"h={service.node.address},{dsn}"

    effective_recursion_method = recursion_method
    if recursion_method == "dsn":
        stripped_dsn = dsn.rstrip(",")
        dsn_table_part = (dsn_table or "").strip() or DSN_TABLE_DEFAULT
        effective_recursion_method = f"dsn={stripped_dsn},{dsn_table_part}"

    prefix = [dsn]
    if effective_recursion_method:
        prefix.append(f"--recursion-method={effective_recursion_method}")
    prefix.extend(extra_remaining_args)
    return prefix


def build_checksums_spec(
    form: ChecksumsForm, resolved: ResolvedEntities
) -> RunCommandSpec:
    """Build the ``pt-table-checksum`` run-command spec from the validated form.

    The framework's ``assemble_envelope`` fills ``target`` (the executor
    ``HostRef``), ``_service_name``, and the connectivity keys around this spec;
    here we own only the command, the ``shlex.join``'d args (the entity-derived
    prefix followed by the form's declarative value/flag args), and the
    ``_service_host`` / ``_service_port`` extras.

    :param form: The validated create form (a ``ChecksumsForm``).
    :param resolved: The entities resolved from the form's reference fields; its
        ``service`` is the ``ServiceRef`` selection (always present — the field is
        required).
    :return: The run-command spec consumed by ``assemble_envelope``.
    """
    service = resolved.service
    args = build_checksums_arg_prefix(
        service,
        recursion_method=form.recursion_method,
        dsn_table=form.dsn_table,
    ) + build_command_args(form)
    return RunCommandSpec(
        command="pt-table-checksum",
        args=shlex.join(args),
        extra_meta={
            "_service_host": service.node.address,
            "_service_port": service.port,
        },
    )
