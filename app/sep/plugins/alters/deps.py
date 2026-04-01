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

"""Define dependencies for the Alters plugin."""

import json
import logging
import shlex
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Form

from app.inventory.models import ServiceTypeEnum
from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
    get_created_entity,
    get_task_by_name,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import Task, TaskBackendEnum, TaskOwner, TaskWrite

logger = logging.getLogger(__name__)


def _build_dsn_with_service(
    dsn_base: str, service_address: str, service_port: int | None
) -> str:
    """Build a DSN string with service information (host and port) if needed.

    :param dsn_base: The base DSN string (e.g., "D=schema,t=table" or "D=percona,t=dsns").
    :type dsn_base: str
    :param service_address: The service node address.
    :type service_address: str
    :param service_port: The service port, if available.
    :type service_port: int | None
    :return: The constructed DSN string with service information if not already present.
    :rtype: str
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


async def build_alters_task_payload(
    form: Annotated[AltersCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the alter task payload from form.

    Build the payload for an Alters task to be executed, including the
    necessary command arguments for performing schema changes.

    :param form: The form data for the Alters creation.
    :type form: AltersCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    :return: A fully constructed `TaskWrite` object containing all the necessary
        commands and parameters for the Alters task execution.
    :rtype: TaskWrite
    """
    service = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        form.service_id,
        type=ServiceTypeEnum.MYSQL,
    )
    schema_name: str
    table_name: str
    if form.schema_id and form.table_id:
        schema = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SCHEMA,
            form.schema_id,
            service_id=service.id,
        )
        table = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.TABLE,
            form.table_id,
            schema_id=schema.id,
        )
        schema_name = schema.name
        table_name = table.name
    else:
        schema_name = (form.schema_name or "").strip()
        table_name = (form.table_name or "").strip()
        if not schema_name or not table_name:
            raise ValueError(
                "Either schema/table IDs or schema_name/table_name must be provided."
            )
    dsn = _build_dsn_with_service(
        f"D={schema_name},t={table_name}", service.node.address, service.port
    )

    if form.recursion_method == "dsn":
        dsn_table = _build_dsn_with_service(
            form.dsn_table, service.node.address, service.port
        )
        form.recursion_method = f"dsn={dsn_table}"

    mysql_defaults_path = (
        form.pre_checks_mysql_config_file or ""
    ).strip() or "~/.my.cnf"
    args = []
    if mysql_defaults_path != "~/.my.cnf":
        args.append(f"--defaults-file={mysql_defaults_path}")

    args.extend(
        [
            f"--alter={form.alter}",
            dsn,
            f"--recursion-method={form.recursion_method}",
        ]
    )

    # Mapping form fields to their respective arguments
    optional_args = {
        "pause_file": f"--pause-file={form.pause_file}",
        "new_table_name": f"--new-table-name={form.new_table_name}",
        "tries": f"--tries={form.tries}",
        "set_vars": f"--set-vars={form.set_vars}",
        "critical_load": f"--critical-load={form.critical_load}",
        "max_load": f"--max-load={form.max_load}",
        "chunk_time": f"--chunk-time={form.chunk_time}",
        "max_lag": f"--max-lag={form.max_lag}",
        "max_flow_ctl": f"--max-flow-ctl={form.max_flow_ctl}",
    }

    # Adding optional arguments if their values exist
    args.extend(arg for key, arg in optional_args.items() if getattr(form, key))

    # Adding flag arguments (no value needed, just presence)
    flag_args = {
        "print_arg": "--print",
        "no_swap_tables": "--no-swap-tables",
        "no_drop_old_table": "--no-drop-old-table",
        "no_drop_new_table": "--no-drop-new-table",
        "no_drop_triggers": "--no-drop-triggers",
    }

    # Adding flag arguments if set to True
    args.extend(arg for key, arg in flag_args.items() if getattr(form, key))

    # Adding '--progress' argument if 'print_arg' is set
    if form.print_arg:
        args.append(f"--progress={form.progress}")

    if form.extra_args:
        extra_args_list = shlex.split(form.extra_args)
        args.extend(extra_args_list)

    args.append("--execute")
    return TaskWrite(
        owner=TaskOwner.ALTERS,
        backend=TaskBackendEnum.PROXY,
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-online-schema-change",
                "args": shlex.join(args),
                "target": form.hostname,
                "_schema_name": schema_name,
                "_table_name": table_name,
                "_service_host": service.node.address,
                "_service_port": service.port,
                "_pre_checks_mysql_config_file": (
                    (form.pre_checks_mysql_config_file or "").strip() or "~/.my.cnf"
                ),
            },
        },
        name=form.task_name,
        target=form.hostname,
        alert_on_fail=form.alert_on_fail,
    )


AltersGeneratedTask = Annotated[TaskWrite, Depends(build_alters_task_payload)]


async def get_alters_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Fetch and validate a task for the Alters plugin.

    This function retrieves a task by its name from the Tasks API and validates
    that it is owned by the Alters plugin. If the task does not exist or is not
    owned by Alters, it raises a 404 HTTP exception.

    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :type tasks_api: TaskAPI
    :return: The retrieved task.
    :rtype: Task
    :raises HTTPNotFoundException: If the task is not found or is not owned by Alters.
    """
    return await get_task_by_name(tasks_api, task_name, TaskOwner.ALTERS)


AltersTask = Annotated[Task, Depends(get_alters_task)]


def get_alters_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Alters plugin.

    Processes the task data to extract hostname and table information.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing hostname and table information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]

    return {
        "hostname": meta["target"],
        "table": f"{meta['_schema_name']}.{meta['_table_name']}",
        "parent": data.get("parent"),
    }


def extract_service_info(meta: dict[str, Any]) -> dict[str, Any]:
    """Extract service information from task configuration.

    :param meta: The task meta containing service information and args string.
    :type meta: dict[str, Any]
    :return: A dictionary containing service_host, service_port, schema_name, and table_name.
    :rtype: dict[str, Any]
    """
    service_host = meta.get("_service_host", "")
    service_port = meta.get("_service_port", 0)
    schema_name = meta.get("_schema_name", "")
    table_name = meta.get("_table_name", "")

    if not service_host or service_port == 0:
        args_string = meta.get("args", "")
        if args_string:
            args = shlex.split(args_string)

            for task_arg in args:
                if "=" in task_arg and not task_arg.startswith("--"):
                    for param in task_arg.split(","):
                        if "=" in param:
                            key, value = param.split("=", 1)
                            if key == "h" and not service_host:
                                service_host = value
                            elif key == "P" and service_port == 0:
                                service_port = int(value)
    if service_host == "":
        service_host = "localhost"
    return {
        "service_host": service_host,
        "service_port": service_port,
        "schema_name": schema_name,
        "table_name": table_name,
    }


def alters_executor_matches_service_host(
    meta: dict[str, Any],
    executor_hosts: Any,
) -> bool:
    """Return whether the task executor is the same host as the MySQL service.

    Same rule as the alters detail page (pre-checks confirm dialog): resolve
    `target` via Nomad `/hosts/` (node name → address) and compare to
    `extract_service_info` host (inventory and/or DSN in `args`).

    :param meta: Task ``meta`` (``target``, ``_service_host``, ``args``, etc.).
    :type meta: dict[str, Any]
    :param executor_hosts: Host map from ``GET /hosts/`` (node name → address),
        or a non-dict fallback where ``target`` is used as the address.
    :type executor_hosts: Any
    :return: ``True`` if the resolved executor address equals the service host.
    :rtype: bool
    """
    service_host = extract_service_info(meta)["service_host"]
    executor_target = meta.get("target") or ""
    if isinstance(executor_hosts, dict):
        executor_address = executor_hosts.get(executor_target, executor_target)
    else:
        executor_address = executor_target
    return executor_address == service_host


_PRE_CHECKS_SCRIPT_PATH = Path(__file__).resolve().parent / "pre_checks.py"


async def build_pre_checks_task(
    base_task: AltersGeneratedTask,
    task_api: TaskAPI,
) -> TaskWrite:
    """Build the Alters pre-checks ``TaskWrite`` from the execute task payload.

    Used as a FastAPI dependency (``AltersPreChecksTask``) and wired with the
    same ``Depends`` as route parameters named ``task`` or ``updated_task`` /
    ``tasks_api``, so the generated task and API client are cached once per
    request.

    Fetches executor hosts, composes inline YAML ``config``, and sets
    ``run-python`` payload/requirements/parent.

    :param base_task: The execute (pt-osc) task from the form; copied on the
        return value only (``base_task`` is not mutated).
    :type base_task: AltersGeneratedTask
    :param task_api: Tasks API client (for ``GET /hosts/``).
    :type task_api: TaskAPI
    :return: Pre-checks task ready to POST or PUT.
    :rtype: TaskWrite
    """
    execute_task_name = base_task.name
    pre_checks_task = base_task.model_copy(deep=True)
    pre_checks_task.name = f"{execute_task_name}-pre-checks"
    pre_checks_task.data["task"] = "run-python"
    del pre_checks_task.data["meta"]["command"]
    del pre_checks_task.data["meta"]["args"]
    meta = pre_checks_task.data["meta"]
    db_host = meta.get("_service_host", "")
    db_port = meta.get("_service_port")
    executor_hosts = await task_api.get("/hosts/")
    skip_fs_checks = not alters_executor_matches_service_host(
        base_task.data["meta"], executor_hosts
    )
    pre_checks_config_lines = [
        f"schema: {meta['_schema_name']}",
        f"table: {meta['_table_name']}",
        f"host: {db_host or '127.0.0.1'}",
    ]
    if db_port is not None:
        pre_checks_config_lines.append(f"port: {db_port}")
    if skip_fs_checks:
        pre_checks_config_lines.append("skip_filesystem_checks: true")
    mysql_cnf = meta.get("_pre_checks_mysql_config_file") or "~/.my.cnf"
    pre_checks_config_lines.append(f"mysql_config_file: {json.dumps(mysql_cnf)}")
    pre_checks_task.data["meta"]["config"] = "\n".join(pre_checks_config_lines)
    pre_checks_task.data["meta"]["requirements"] = (
        "packaging\nPyYAML\nPyMySQL[rsa,ed25519]"
    )
    pre_checks_task.data["payload"] = f"file://{_PRE_CHECKS_SCRIPT_PATH}"
    pre_checks_task.data["parent"] = execute_task_name
    return pre_checks_task


AltersPreChecksTask = Annotated[TaskWrite, Depends(build_pre_checks_task)]


def parse_single_arg(arg: str, form_values: dict[str, Any]) -> None:
    """Parse a single argument and update form values.

    :param arg: The argument string to parse.
    :type arg: str
    :param form_values: The form values dictionary to update.
    :type form_values: dict[str, Any]
    """
    if arg.startswith("--recursion-method="):
        recursion_method = arg.split("=", 1)[1]
        if recursion_method.startswith("dsn="):
            form_values["recursion_method"] = "dsn"
            dsn_value = recursion_method.split("=", 1)[1]
            dsn_parts = [
                part
                for part in dsn_value.split(",")
                if not part.startswith(("h=", "P="))
            ]
            form_values["dsn_table"] = ",".join(dsn_parts) if dsn_parts else dsn_value
        else:
            form_values["recursion_method"] = recursion_method
        return

    arg_mappings = {
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

    for arg_pattern, field_name in arg_mappings.items():
        if arg.startswith(arg_pattern):
            form_values[field_name] = arg.split("=", 1)[1]
            return

    flag_mappings = {
        "--print": "print_arg",
        "--no-swap-tables": "no_swap_tables",
        "--no-drop-old-table": "no_drop_old_table",
        "--no-drop-new-table": "no_drop_new_table",
        "--no-drop-triggers": "no_drop_triggers",
    }

    for flag, field_name in flag_mappings.items():
        if arg == flag:
            form_values[field_name] = True
            return


def parse_alters_task_args(meta: dict[str, Any]) -> dict[str, Any]:
    """Parse existing task arguments back into form field values.

    Extracts form field values from the task configuration arguments for editing.

    :param meta: The task meta containing the args string.
    :type meta: dict[str, Any]
    :return: A dictionary containing form field values.
    :rtype: dict[str, Any]
    """
    form_values = {
        "alter": "",
        "recursion_method": "processlist",
        "dsn_table": "",
        "pause_file": "",
        "new_table_name": "",
        "print_arg": False,
        "progress": "",
        "no_swap_tables": False,
        "no_drop_old_table": False,
        "no_drop_new_table": False,
        "no_drop_triggers": False,
        "tries": "",
        "set_vars": "",
        "critical_load": "",
        "max_load": "",
        "chunk_time": "",
        "max_lag": "",
        "max_flow_ctl": "",
        "extra_args": "",
    }

    args_string = meta.get("args", "")
    if not args_string:
        return form_values

    args = shlex.split(args_string)

    known_args_patterns = {
        "--alter=",
        "--recursion-method=",
        "--progress=",
        "--pause-file=",
        "--new-table-name=",
        "--tries=",
        "--set-vars=",
        "--critical-load=",
        "--max-load=",
        "--chunk-time=",
        "--max-lag=",
        "--max-flow-ctl=",
        "--print",
        "--no-swap-tables",
        "--no-drop-old-table",
        "--no-drop-new-table",
        "--no-drop-triggers",
        "--execute",
        "--dry-run",
    }

    extra_args_list = []

    for arg in args:
        if not arg.startswith("--") and "=" in arg:
            continue

        is_known = False
        if arg in known_args_patterns:
            is_known = True
        else:
            for pattern in known_args_patterns:
                if pattern.endswith("=") and arg.startswith(pattern):
                    is_known = True
                    break

        if is_known:
            parse_single_arg(arg, form_values)
        elif arg not in ["--execute", "--dry-run"]:
            extra_args_list.append(arg)

    if extra_args_list:
        form_values["extra_args"] = shlex.join(extra_args_list)

    return form_values


async def get_alters_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> dict[str, Any]:
    """Assemble the context for the Alters plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Alters-specific information.
    :type context: DefaultContext
    :param executor_hosts_ctx: The executor hosts context for the Alters tasks.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: An updated context dictionary containing Alters-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_alters_task_info,
        executor_hosts_ctx,
        context,
        TaskOwner.ALTERS,
        alert_on_fail_default=True,
    )
