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

"""Build the ``run-command`` pt-online-schema-change spec for the Alters app.

:func:`build_alters_spec` is the pure ``(form, resolved) -> RunCommandSpec``
builder shared by the JSON create/update routes and the legacy Jinja form path
(both via the impure, inventory-resolving
:func:`~app.sep.apps.alters.deps.build_alters_task`), so a parent execute task's
Nomad payload is byte-identical regardless of call origin. The framework's
``build_command_args`` renders the declarative value/flag args from the model's
``ArgFormat`` markers; only the alters-specific DSN/``--alter`` prefix and the
``--progress``/``extra_args``/``--execute`` suffix that frame it stay bespoke
here. The framework's ``assemble_envelope`` supplies the executor ``target``,
``_service_name``, and the connectivity meta keys around this spec.
"""

import shlex

from app.sep.apps.alters.models import AltersCreate
from app.sep.apps.framework.form_dsl import DSN_TABLE_DEFAULT
from app.sep.apps.framework.spec import (
    build_command_args,
    ResolvedEntities,
    RunCommandSpec,
)


def _build_dsn_with_service(
    dsn_base: str, service_address: str, service_port: int | None
) -> str:
    """Build a DSN string with service information (host and port) if needed.

    :param dsn_base: The base DSN string (e.g., ``D=schema,t=table`` or ``D=percona,t=dsns``).
    :param service_address: The service node address.
    :param service_port: The service port, if available.
    :return: The constructed DSN string with service information if not already present.
    """
    if dsn_base.startswith(("h=", "P=")):
        return dsn_base

    service_dsn = ""
    if service_address != "localhost":
        service_dsn = f"h={service_address}"
    if service_port is not None:
        if service_dsn:
            service_dsn = f"{service_dsn},P={service_port}"
        else:
            service_dsn = f"P={service_port}"

    if service_dsn:
        return f"{service_dsn},{dsn_base}"

    return dsn_base


def build_alters_spec(form: AltersCreate, resolved: ResolvedEntities) -> RunCommandSpec:
    """Build the ``pt-online-schema-change`` run-command spec from the validated form.

    The framework's ``assemble_envelope`` fills ``target`` (the executor
    ``HostRef``), ``_service_name``, and the connectivity keys around this spec;
    here we own only the command, the ``shlex.join``'d args, and the alters-only
    ``_command_line`` / ``_schema_name`` / ``_table_name`` / ``_service_host`` /
    ``_service_port`` / ``_pre_checks_mysql_config_file`` extras. The args frame
    the framework's declarative value/flag args (:func:`build_command_args`) with
    an alters-specific prefix (``--defaults-file`` when non-default, ``--alter``,
    the target DSN, ``--recursion-method``) and suffix (``--progress`` when set,
    ``extra_args`` tokens, ``--execute``).

    :param form: The validated create form (an ``AltersCreate``).
    :param resolved: The entities resolved from the form's reference fields; its
        ``service`` is the ``ServiceRef`` selection, and ``db_schema`` / ``db_table``
        resolve to the inventory entity name or fall back to the free-typed value.
    :return: The run-command spec consumed by ``assemble_envelope``.
    """
    service = resolved.service
    schema_entity = resolved.entities.get("db_schema")
    table_entity = resolved.entities.get("db_table")
    schema_name = schema_entity.name if schema_entity else str(form.db_schema)
    table_name = table_entity.name if table_entity else str(form.db_table)

    dsn = _build_dsn_with_service(
        f"D={schema_name},t={table_name}", service.node.address, service.port
    )

    effective_recursion_method = form.recursion_method
    if form.recursion_method == "dsn":
        dsn_table_base = (form.dsn_table or "").strip() or DSN_TABLE_DEFAULT
        dsn_table = _build_dsn_with_service(
            dsn_table_base, service.node.address, service.port
        )
        effective_recursion_method = f"dsn={dsn_table}"

    mysql_defaults_path = (
        form.pre_checks_mysql_config_file or ""
    ).strip() or "~/.my.cnf"

    prefix = []
    if mysql_defaults_path != "~/.my.cnf":
        prefix.append(f"--defaults-file={mysql_defaults_path}")
    prefix.extend(
        [
            f"--alter={form.alter}",
            dsn,
            f"--recursion-method={effective_recursion_method}",
        ]
    )

    suffix = []
    if form.progress:
        suffix.append(f"--progress={form.progress}")
    if form.extra_args:
        suffix.extend(shlex.split(form.extra_args))
    suffix.append("--execute")

    args = shlex.join(prefix + build_command_args(form) + suffix)
    return RunCommandSpec(
        command="pt-online-schema-change",
        args=args,
        extra_meta={
            "_command_line": f"pt-online-schema-change {args}",
            "_schema_name": schema_name,
            "_table_name": table_name,
            "_service_host": service.node.address,
            "_service_port": service.port,
            "_pre_checks_mysql_config_file": mysql_defaults_path,
        },
    )
