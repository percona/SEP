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
JSON path (:func:`build_checksums_payload` / :func:`build_checksums_spec`) and the
legacy Jinja form path (``deps.assemble_checksum_payload``); the declarative
value/flag args come from :func:`build_checksums_command_args`, which emits
``--databases`` / ``--tables`` from resolved multi-value reference fields then
delegates the remaining markers to the framework's
:func:`~app.sep.apps.framework.spec.build_command_args`, so a checksum task's
Nomad payload is byte-identical regardless of the call origin. The framework's
``assemble_envelope`` supplies the executor ``target``, ``_service_name``, and the
connectivity meta keys, byte-uniform with the canonical hand-written envelope.
"""

import shlex
from collections.abc import Iterable

from app.core.utils.cli_args import render_value_arg
from app.sep.apps.checksums.models import ChecksumsForm
from app.sep.apps.framework.form_dsl import DSN_TABLE_DEFAULT
from app.sep.apps.framework.spec import (
    build_command_args,
    ResolvedEntities,
    RunCommandSpec,
)
from app.sep.deps import get_created_entity, InventoryAPI
from app.sep.inventory import CreatedService
from app.sep.models import SyncInventoryEntityTypeEnum

_DATABASES_ARG = "--databases=${value}"
_TABLES_ARG = "--tables=${value}"


async def resolve_checksums_target_args(
    form: ChecksumsForm,
    inventory_api: InventoryAPI,
) -> tuple[str, str]:
    """Resolve multi-value schema/table refs to comma-separated CLI arg values.

    :param form: The validated checksums create form.
    :param inventory_api: The inventory API client.
    :return: ``(databases_arg, tables_arg)`` suitable for ``--databases=`` /
        ``--tables=`` emission; either may be empty when unset.
    """
    databases_arg = await _resolve_schema_names(form.databases, inventory_api)
    tables_arg = await _resolve_table_names(form.tables, inventory_api)
    return databases_arg, tables_arg


async def _resolve_schema_names(
    values: list[int | str],
    inventory_api: InventoryAPI,
) -> str:
    """Join inventory schema ids and free-typed names into a ``--databases`` value."""
    if not values:
        return ""
    names: list[str] = []
    for value in values:
        if isinstance(value, int):
            schema = await get_created_entity(
                inventory_api,
                SyncInventoryEntityTypeEnum.SCHEMA,
                value,
            )
            names.append(schema.name)
        else:
            names.append(value)
    return ",".join(names)


async def _resolve_table_names(
    values: list[int | str],
    inventory_api: InventoryAPI,
) -> str:
    """Join inventory table ids and free-typed names into a ``--tables`` value."""
    if not values:
        return ""
    schema_names: dict[int, str] = {}
    entries: list[str] = []
    for value in values:
        if isinstance(value, int):
            table = await get_created_entity(
                inventory_api,
                SyncInventoryEntityTypeEnum.TABLE,
                value,
            )
            schema_name = schema_names.get(table.schema_id)
            if schema_name is None:
                schema = await get_created_entity(
                    inventory_api,
                    SyncInventoryEntityTypeEnum.SCHEMA,
                    table.schema_id,
                )
                schema_name = schema.name
                schema_names[table.schema_id] = schema_name
            entries.append(f"{schema_name}.{table.name}")
        else:
            entries.append(value)
    return ",".join(entries)


def build_checksums_command_args(
    form: ChecksumsForm,
    *,
    databases_arg: str = "",
    tables_arg: str = "",
) -> list[str]:
    """Assemble checksums CLI args from resolved targets plus declarative markers.

    Emit ``--databases`` and ``--tables`` first (when non-empty), in field-declaration
    order, then the remaining ``ArgFormat`` value args and flag args from the form.

    :param form: The validated checksums create form.
    :param databases_arg: The resolved comma-separated database names.
    :param tables_arg: The resolved comma-separated ``schema.table`` strings.
    :return: The ordered argument list ready to follow the entity-derived prefix.
    """
    target_value_args: list[str] = []
    if databases_arg:
        target_value_args.extend(render_value_arg(_DATABASES_ARG, databases_arg))
    if tables_arg:
        target_value_args.extend(render_value_arg(_TABLES_ARG, tables_arg))
    return target_value_args + build_command_args(form)


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
    args follow via :func:`build_checksums_command_args`.

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
    form: ChecksumsForm,
    resolved: ResolvedEntities,
    *,
    databases_arg: str = "",
    tables_arg: str = "",
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
    :param databases_arg: The resolved comma-separated database names for
        ``--databases=``.
    :param tables_arg: The resolved comma-separated ``schema.table`` strings for
        ``--tables=``.
    :return: The run-command spec consumed by ``assemble_envelope``.
    """
    service = resolved.service
    args = build_checksums_arg_prefix(
        service,
        recursion_method=form.recursion_method,
        dsn_table=form.dsn_table,
    ) + build_checksums_command_args(
        form,
        databases_arg=databases_arg,
        tables_arg=tables_arg,
    )
    return RunCommandSpec(
        command="pt-table-checksum",
        args=shlex.join(args),
        extra_meta={
            "_service_host": service.node.address,
            "_service_port": service.port,
        },
    )
