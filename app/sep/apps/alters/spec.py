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

"""Build the ``run-command`` pt-online-schema-change task envelope for Alters.

:func:`build_alters_spec` is the pure ``(service, schema_name, table_name, body) ->
TaskWrite`` builder shared by the JSON create/update routes and the legacy Jinja
form path (both via the impure, inventory-resolving
:func:`~app.sep.apps.alters.deps.build_alters_task`), so a parent execute task's
Nomad payload is byte-identical regardless of call origin. The inventory service is
resolved upstream and passed in; this builder performs no I/O.
"""

import shlex

from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.sep.apps.alters.models import AltersCreate
from app.sep.apps.framework.form_dsl import DSN_TABLE_DEFAULT
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.inventory import CreatedService
from app.tasks.models import TaskBackendEnum, TaskOwner, TaskWrite


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


def build_alters_spec(
    service: CreatedService,
    schema_name: str,
    table_name: str,
    body: AltersCreate,
) -> TaskWrite:
    """Assemble a parent execute ``TaskWrite`` from pre-resolved inputs.

    Both the Jinja form path and the JSON API path delegate here so Nomad
    payloads are byte-identical regardless of call origin.

    :param service: The validated inventory service instance.
    :param schema_name: The target schema name.
    :param table_name: The target table name.
    :param body: The alters create/write payload.
    :return: A fully constructed parent execute ``TaskWrite``.
    """
    dsn = _build_dsn_with_service(
        f"D={schema_name},t={table_name}", service.node.address, service.port
    )

    effective_recursion_method = body.recursion_method
    if body.recursion_method == "dsn":
        dsn_table_base = (body.dsn_table or "").strip() or DSN_TABLE_DEFAULT
        dsn_table = _build_dsn_with_service(
            dsn_table_base, service.node.address, service.port
        )
        effective_recursion_method = f"dsn={dsn_table}"

    mysql_defaults_path = (
        body.pre_checks_mysql_config_file or ""
    ).strip() or "~/.my.cnf"
    args = []
    if mysql_defaults_path != "~/.my.cnf":
        args.append(f"--defaults-file={mysql_defaults_path}")

    args.extend(
        [
            f"--alter={body.alter}",
            dsn,
            f"--recursion-method={effective_recursion_method}",
        ]
    )

    optional_args = {
        "pause_file": f"--pause-file={body.pause_file}",
        "new_table_name": f"--new-table-name={body.new_table_name}",
        "tries": f"--tries={body.tries}",
        "set_vars": f"--set-vars={body.set_vars}",
        "critical_load": f"--critical-load={body.critical_load}",
        "max_load": f"--max-load={body.max_load}",
        "chunk_time": f"--chunk-time={body.chunk_time}",
        "max_lag": f"--max-lag={body.max_lag}",
        "max_flow_ctl": f"--max-flow-ctl={body.max_flow_ctl}",
    }
    args.extend(arg for key, arg in optional_args.items() if getattr(body, key))

    flag_args = {
        "print_arg": "--print",
        "no_swap_tables": "--no-swap-tables",
        "no_drop_old_table": "--no-drop-old-table",
        "no_drop_new_table": "--no-drop-new-table",
        "no_drop_triggers": "--no-drop-triggers",
    }
    args.extend(arg for key, arg in flag_args.items() if getattr(body, key))

    if body.progress:
        args.append(f"--progress={body.progress}")

    if body.extra_args:
        args.extend(shlex.split(body.extra_args))

    args.append("--execute")
    return TaskWrite(
        owner=TaskOwner.ALTERS,
        backend=TaskBackendEnum.PROXY,
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-online-schema-change",
                "args": shlex.join(args),
                "_command_line": f"pt-online-schema-change {shlex.join(args)}",
                "target": body.hostname,
                "_schema_name": schema_name,
                "_table_name": table_name,
                "_service_name": service.name,
                "_service_host": service.node.address,
                "_service_port": service.port,
                "_pre_checks_mysql_config_file": mysql_defaults_path,
                CONNECTIVITY_META_HOST_KEY: service.node.address,
                CONNECTIVITY_META_PORT_KEY: service.port or DEFAULT_MYSQL_PORT,
                CONNECTIVITY_META_SERVICE_TYPE_KEY: service.type.value,
            },
        },
        name=body.task_name,
        target=body.hostname,
        alert_on_fail=body.alert_on_fail,
    )
