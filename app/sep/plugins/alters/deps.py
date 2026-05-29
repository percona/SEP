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
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Form, HTTPException

from app.core.exceptions import HTTPConflictException
from app.core.requests.remote_api import RemoteAPI
from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.deps import (
    check_for_conflicted_running_tasks,
    DefaultContext,
    ExecutorHostsCtx,
    get_created_entity,
    get_task_by_name,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.sep.inventory import CreatedService
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.alters.models import (
    AltersCreate,
    AltersTaskResponse,
    AltersTaskWrite,
)
from app.sep.plugins.alters.schema import alters_schema
from app.sep.plugins.framework import ConnectivityWarning
from app.sep.plugins.framework.cascade import (
    build_derived_payload,
    build_predecessor_payload,
    cascade_delete_tasks,
    cascade_update_tasks,
    CascadeFailure,
    CascadeResult,
)
from app.sep.plugins.framework.schema import ChainedPredecessor
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)

DEFAULT_RECURSION_DSN_TABLE = "D=percona,t=dsns"


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


async def _resolve_schema_table_names(
    body: AltersCreate | AltersTaskWrite,
    inventory_api: InventoryAPI,
    service: CreatedService,
) -> tuple[str, str]:
    """Resolve schema and table names from inventory IDs or manual fields.

    :param body: The alters create/write payload.
    :type body: AltersCreate | AltersTaskWrite
    :param inventory_api: The Inventory API client.
    :type inventory_api: InventoryAPI
    :param service: The validated MySQL service.
    :type service: CreatedService
    :return: The resolved ``(schema_name, table_name)`` pair.
    :rtype: tuple[str, str]
    :raises ValueError: When neither IDs nor manual names are provided.
    """
    if body.schema_id and body.table_id:
        schema = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SCHEMA,
            body.schema_id,
            service_id=service.id,
        )
        table = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.TABLE,
            body.table_id,
            schema_id=schema.id,
        )
        return schema.name, table.name

    schema_name = (body.schema_name or "").strip()
    table_name = (body.table_name or "").strip()
    if not schema_name or not table_name:
        raise ValueError(
            "Either schema/table IDs or schema_name/table_name must be provided."
        )
    return schema_name, table_name


def _assemble_alters_payload(
    service: CreatedService,
    schema_name: str,
    table_name: str,
    body: AltersCreate | AltersTaskWrite,
) -> TaskWrite:
    """Assemble a parent execute ``TaskWrite`` from pre-resolved inputs.

    Both the Jinja form path and the JSON API path delegate here so Nomad
    payloads are byte-identical regardless of call origin.

    :param service: The validated inventory service instance.
    :type service: CreatedService
    :param schema_name: The target schema name.
    :type schema_name: str
    :param table_name: The target table name.
    :type table_name: str
    :param body: The alters create/write payload.
    :type body: AltersCreate | AltersTaskWrite
    :return: A fully constructed parent execute ``TaskWrite``.
    :rtype: TaskWrite
    """
    dsn = _build_dsn_with_service(
        f"D={schema_name},t={table_name}", service.node.address, service.port
    )

    effective_recursion_method = body.recursion_method
    if body.recursion_method == "dsn":
        dsn_table_base = (body.dsn_table or "").strip() or DEFAULT_RECURSION_DSN_TABLE
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

    if body.print_arg:
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


async def build_alters_task(
    body: AltersCreate | AltersTaskWrite,
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the parent alters execute task from a form or JSON payload.

    :param body: The alters create/write payload.
    :type body: AltersCreate | AltersTaskWrite
    :param inventory_api: The Inventory API client.
    :type inventory_api: InventoryAPI
    :return: A fully constructed parent execute ``TaskWrite``.
    :rtype: TaskWrite
    """
    service = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        body.service_id,
        type=ServiceTypeEnum.MYSQL,
    )
    schema_name, table_name = await _resolve_schema_table_names(
        body, inventory_api, service
    )
    return _assemble_alters_payload(service, schema_name, table_name, body)


async def build_alters_task_payload(
    form: Annotated[AltersCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the alter task payload from a Jinja form submission.

    :param form: The form data for the Alters creation.
    :type form: AltersCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    :return: A fully constructed ``TaskWrite`` object containing all the necessary
        commands and parameters for the Alters task execution.
    :rtype: TaskWrite
    """
    return await build_alters_task(form, inventory_api)


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
    ``target`` via Nomad ``/hosts/`` (node name → address) and compare to
    ``extract_service_info`` host (inventory and/or DSN in ``args``).

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


async def build_pre_checks_task_payload(
    base_task: TaskWrite,
    *,
    task_api: TaskAPI,
) -> TaskWrite:
    """Build the imperative pre-checks ``TaskWrite`` from the parent execute task.

    Transforms the parent ``run-command`` payload into ``run-python``, fetches
    executor hosts, composes inline YAML ``config``, and sets script
    requirements. The caller is responsible for naming and ``parent`` linkage
    (Jinja routes set these directly; cascade uses
    :func:`build_predecessor_payload`).

    :param base_task: The parent execute (pt-osc) task; copied on the return
        value only (``base_task`` is not mutated).
    :type base_task: TaskWrite
    :param task_api: Tasks API client (for ``GET /hosts/``).
    :type task_api: TaskAPI
    :return: Pre-checks task payload ready for POST or PUT.
    :rtype: TaskWrite
    """
    pre_checks_task = base_task.model_copy(deep=True)
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
    return pre_checks_task


async def build_pre_checks_task(
    base_task: AltersGeneratedTask,
    task_api: TaskAPI,
) -> TaskWrite:
    """Build the Alters pre-checks ``TaskWrite`` from the execute task payload.

    Used as a FastAPI dependency (``AltersPreChecksTask``) and wired with the
    same ``Depends`` as route parameters named ``task`` or ``updated_task`` /
    ``tasks_api``, so the generated task and API client are cached once per
    request.

    :param base_task: The execute (pt-osc) task from the form.
    :type base_task: AltersGeneratedTask
    :param task_api: Tasks API client (for ``GET /hosts/``).
    :type task_api: TaskAPI
    :return: Pre-checks task ready to POST or PUT.
    :rtype: TaskWrite
    """
    pre_checks_task = await build_pre_checks_task_payload(base_task, task_api=task_api)
    pre_checks_task.name = f"{base_task.name}-pre-checks"
    pre_checks_task.data["parent"] = base_task.name
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


def alters_derived_task_names(parent_name: str) -> list[str]:
    """Return stored derived task names for a parent alters task.

    :param parent_name: The parent execute task name.
    :type parent_name: str
    :return: Derived task names derived from ``alters_schema.derived``.
    :rtype: list[str]
    """
    return [f"{parent_name}{spec.name_suffix}" for spec in alters_schema.derived or []]


def alters_predecessor_task_names(parent_name: str) -> list[str]:
    """Return stored predecessor task names for a parent alters task.

    :param parent_name: The parent execute task name.
    :type parent_name: str
    :return: Predecessor task names derived from ``alters_schema.predecessors``.
    :rtype: list[str]
    """
    return [
        f"{parent_name}{spec.name_suffix}" for spec in alters_schema.predecessors or []
    ]


def alters_satellite_task_names(parent_name: str) -> list[str]:
    """Return all satellite task names (derived + predecessors) for a parent.

    :param parent_name: The parent execute task name.
    :type parent_name: str
    :return: Derived and predecessor task names for cascade delete.
    :rtype: list[str]
    """
    return alters_derived_task_names(parent_name) + alters_predecessor_task_names(
        parent_name
    )


def resolve_predecessor_spec(
    body: AltersCreate | AltersTaskWrite,
) -> ChainedPredecessor:
    """Resolve the effective chained-predecessor spec for one submission.

    Applies the user-overridable ``continue_on_pre_check_failure`` toggle on
    top of the schema's default ``on_failure="halt"`` policy.

    :param body: The alters create/write payload.
    :type body: AltersCreate | AltersTaskWrite
    :return: The ``ChainedPredecessor`` spec to use for cascade wiring.
    :rtype: ChainedPredecessor
    """
    schema_spec = (alters_schema.predecessors or [None])[0]
    if schema_spec is None:
        raise ValueError("alters_schema must declare at least one predecessor")
    if body.continue_on_pre_check_failure:
        return ChainedPredecessor(
            name_suffix=schema_spec.name_suffix,
            on_failure="continue",
            parent_link=schema_spec.parent_link,
        )
    return schema_spec


_PRE_CHECKS_AUTO_FIRE_FAILED_MESSAGE = (
    "Task group was created, but automatic pre-checks could not be started. "
    "Run Pre-checks from the task detail page."
)


async def cascade_create_alters_group(
    tasks_api: RemoteAPI,
    parent_task: TaskWrite,
    pre_checks_template: TaskWrite,
    body: AltersCreate | AltersTaskWrite,
) -> str | None:
    """POST parent + dry-run + pre-checks, then fire the pre-checks chain.

    Atomically creates the three-task group, then best-effort fires
    ``POST /execute/{parent}-pre-checks`` to chain into the parent run task.
    Rolls back already-created tasks when any of the three POSTs fail; a
    failure on the execute call leaves the persisted group intact.

    :param tasks_api: The Tasks API client.
    :type tasks_api: RemoteAPI
    :param parent_task: The parent execute task payload.
    :type parent_task: TaskWrite
    :param pre_checks_template: The imperative pre-checks payload from
        :func:`build_pre_checks_task_payload`.
    :type pre_checks_template: TaskWrite
    :param body: The alters create/write payload (for ``continue_on_pre_check_failure``).
    :type body: AltersCreate | AltersTaskWrite
    :return: A user-facing warning when auto-fire of pre-checks fails, else ``None``.
    :rtype: str | None
    :raises Exception: Re-raises the underlying Tasks API error after rollback
        when one of the three task POSTs fails.
    """
    parent_payload = parent_task.model_dump()
    derived_specs = alters_schema.derived or []
    predecessor_spec = resolve_predecessor_spec(body)

    created_names: list[str] = []
    predecessor_payload: dict[str, Any]
    try:
        await tasks_api.post("/", json=parent_payload)
        created_names.append(parent_payload["name"])

        for derived_spec in derived_specs:
            child_payload = build_derived_payload(parent_payload, derived_spec)
            await tasks_api.post("/", json=child_payload)
            created_names.append(child_payload["name"])

        predecessor_payload = build_predecessor_payload(
            parent_payload,
            pre_checks_template.model_dump(),
            predecessor_spec,
        )
        await tasks_api.post("/", json=predecessor_payload)
        created_names.append(predecessor_payload["name"])
    except Exception:
        for task_name in reversed(created_names):
            try:
                await tasks_api.delete(f"/{task_name}")
            except Exception as rollback_exc:  # noqa: BLE001
                logger.warning(
                    "Rollback DELETE failed for %r during "
                    "cascade_create_alters_group rollback: %s",
                    task_name,
                    rollback_exc,
                )
        raise

    try:
        await tasks_api.post(
            f"/execute/{predecessor_payload['name']}",
            json={
                "chain_task_names": [parent_payload["name"]],
                "chain_on_failure": predecessor_spec.on_failure == "continue",
            },
        )
    except HTTPException as exc:
        logger.warning(
            "Auto-fire of pre-checks %r failed; task group persisted: %s",
            predecessor_payload["name"],
            exc,
        )
        return _PRE_CHECKS_AUTO_FIRE_FAILED_MESSAGE
    return None


_ALTERS_GROUP_RENAME_MESSAGE = (
    "Cannot rename an alters task group. Delete and recreate the task "
    "instead; the pre-checks chain wired at create time stores task "
    "names verbatim."
)


def ensure_alters_group_update_preserves_names(
    parent_existing_name: str,
    updated_parent_name: str,
) -> None:
    """Refuse parent renames on update; create-time chain stores names verbatim.

    :param parent_existing_name: The current parent task name (PUT URL path).
    :type parent_existing_name: str
    :param updated_parent_name: The parent name from the update payload.
    :type updated_parent_name: str
    :raises HTTPConflictException: When ``updated_parent_name`` differs from
        ``parent_existing_name``.
    """
    if updated_parent_name != parent_existing_name:
        raise HTTPConflictException(_ALTERS_GROUP_RENAME_MESSAGE)


async def cascade_update_alters_group(
    tasks_api: RemoteAPI,
    parent_existing_name: str,
    parent_task: TaskWrite,
    pre_checks_template: TaskWrite,
    body: AltersCreate | AltersTaskWrite,
) -> CascadeResult:
    """PUT the parent, dry-run sibling, and pre-checks predecessor.

    Does not re-fire ``POST /execute`` — chain wiring from create remains
    valid because task names are unchanged.

    :param tasks_api: The Tasks API client.
    :type tasks_api: RemoteAPI
    :param parent_existing_name: The current parent task name.
    :type parent_existing_name: str
    :param parent_task: The updated parent execute payload.
    :type parent_task: TaskWrite
    :param pre_checks_template: The updated imperative pre-checks payload.
    :type pre_checks_template: TaskWrite
    :param body: The alters create/write payload (for ``continue_on_pre_check_failure``).
    :type body: AltersCreate | AltersTaskWrite
    :return: A merged :class:`CascadeResult` across derived and predecessor legs.
    :rtype: CascadeResult
    :raises HTTPConflictException: When the update attempts to rename the parent.
    """
    ensure_alters_group_update_preserves_names(parent_existing_name, parent_task.name)
    parent_payload = parent_task.model_dump()
    derived_specs = alters_schema.derived or []
    derived_names = alters_derived_task_names(parent_existing_name)
    predecessor_names = alters_predecessor_task_names(parent_existing_name)
    predecessor_spec = resolve_predecessor_spec(body)

    derived_result = await cascade_update_tasks(
        tasks_api,
        parent_existing_name,
        parent_payload,
        derived_names,
        derived_specs,
    )
    predecessor_result = CascadeResult()
    for existing_name in predecessor_names:
        built = build_predecessor_payload(
            parent_payload,
            pre_checks_template.model_dump(),
            predecessor_spec,
        )
        try:
            await tasks_api.put(f"/{existing_name}", json=built)
            predecessor_result.successes.append(built["name"])
        except Exception as exc:  # noqa: BLE001
            predecessor_result.failures.append(CascadeFailure(existing_name, exc))
    return CascadeResult(
        successes=[*derived_result.successes, *predecessor_result.successes],
        failures=[*derived_result.failures, *predecessor_result.failures],
    )


async def cascade_delete_alters_group(
    tasks_api: RemoteAPI,
    parent_name: str,
) -> CascadeResult:
    """DELETE derived and predecessor satellites, then the parent task.

    :param tasks_api: The Tasks API client.
    :type tasks_api: RemoteAPI
    :param parent_name: The parent execute task name.
    :type parent_name: str
    :return: A :class:`CascadeResult` recording per-leg outcomes.
    :rtype: CascadeResult
    """
    return await cascade_delete_tasks(
        tasks_api,
        parent_name,
        alters_satellite_task_names(parent_name),
    )


def is_alters_parent_task(task: Task) -> bool:
    """Return whether ``task`` is a parent execute task (not a satellite).

    :param task: The task retrieved from the Tasks API.
    :type task: Task
    :return: ``True`` when the task has no ``data.parent`` link.
    :rtype: bool
    """
    return not task.data.get("parent")


async def resolve_alters_parent_task(task_name: str, tasks_api: TaskAPI) -> Task:
    """Resolve a parent task, following satellite ``data.parent`` links.

    :param task_name: The requested task name (parent or satellite).
    :type task_name: str
    :param tasks_api: The Tasks API client.
    :type tasks_api: TaskAPI
    :return: The parent alters task.
    :rtype: Task
    """
    task = await get_alters_task(task_name, tasks_api)
    parent_name = task.data.get("parent")
    if parent_name:
        return await get_alters_task(parent_name, tasks_api)
    return task


async def get_unprotected_alters_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Return the parent alters task or raise 409 when it is protected.

    Resolves satellite path parameters to the parent execute task before
    applying the protected check so both the JSON API and Jinja form paths
    gate the same record.

    :param task_name: The requested task name (parent or satellite).
    :type task_name: str
    :param tasks_api: The Tasks API client.
    :type tasks_api: TaskAPI
    :raises HTTPConflictException: If the parent task is marked as protected.
    :return: The unprotected parent task.
    :rtype: Task
    """
    parent_task = await resolve_alters_parent_task(task_name, tasks_api)
    if parent_task.protected:
        raise HTTPConflictException("Cannot edit a protected task.")
    return parent_task


UnprotectedAltersTask = Annotated[Task, Depends(get_unprotected_alters_task)]


async def get_deletable_alters_parent_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Return the parent alters task or raise when delete is not allowed.

    Resolves satellite path parameters to the parent execute task, then
    applies the same running-task and protected gates as
    :func:`get_unprotected_alters_task` plus
    :func:`check_for_conflicted_running_tasks`.

    :param task_name: The requested task name (parent or satellite).
    :type task_name: str
    :param tasks_api: The Tasks API client.
    :type tasks_api: TaskAPI
    :raises HTTPConflictException: If the parent is running/pending or protected.
    :return: The deletable parent task.
    :rtype: Task
    """
    parent_task = await resolve_alters_parent_task(task_name, tasks_api)
    await check_for_conflicted_running_tasks(parent_task.name, tasks_api)
    if parent_task.protected:
        raise HTTPConflictException("Cannot delete a protected task.")
    return parent_task


DeletableAltersParent = Annotated[Task, Depends(get_deletable_alters_parent_task)]


def _extract_latest_task_status(
    histories: Iterable[dict[str, Any]],
) -> TaskHistoryStatusEnum | None:
    """Return the latest known status from a task history payload."""
    for history in histories:
        if (status := history.get("status")) is not None:
            return TaskHistoryStatusEnum(status)
    return None


async def get_alters_task_status(
    task_name: str,
    tasks_api: TaskAPI,
) -> TaskHistoryStatusEnum | None:
    """Fetch the latest execution status for an alters task.

    :param task_name: The name of the alters task.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to query task history.
    :type tasks_api: TaskAPI
    :return: The latest known task status, or ``None`` if no history exists.
    :rtype: TaskHistoryStatusEnum | None
    """
    response = await tasks_api.get(f"/{task_name}/history/")
    return _extract_latest_task_status(response["items"])


def _command_line_from_meta(meta: dict[str, Any]) -> str | None:
    """Return the full pt-osc invocation for detail display.

    New tasks store ``_command_line`` at creation time; older tasks are
    synthesized from ``command`` + ``args`` when the API response is built.

    :param meta: The task ``data.meta`` mapping.
    :type meta: dict[str, Any]
    :return: The rendered command line, or ``None`` when unavailable.
    :rtype: str | None
    """
    stored = meta.get("_command_line")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    command = meta.get("command")
    args = meta.get("args")
    if (
        isinstance(command, str)
        and isinstance(args, str)
        and command.strip()
        and args.strip()
    ):
        return f"{command.strip()} {args.strip()}"
    if isinstance(args, str) and args.strip():
        return args.strip()
    if isinstance(command, str) and command.strip():
        return command.strip()
    return None


def build_alters_api_task_response(
    task: Task,
    status: TaskHistoryStatusEnum | None = None,
    *,
    connectivity_warning: ConnectivityWarning | None = None,
    pre_checks_auto_fire_warning: str | None = None,
    username_mapping: dict[str, str] | None = None,
) -> AltersTaskResponse:
    """Build an alters task response object for the JSON API.

    :param task: The alters task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :param connectivity_warning: A warning to surface when a connectivity
        check failed during the task creation flow.
    :type connectivity_warning: ConnectivityWarning | None
    :param pre_checks_auto_fire_warning: A warning when automatic pre-checks
        could not be started after create.
    :type pre_checks_auto_fire_warning: str | None
    :param username_mapping: Optional mapping of user IDs to usernames.
    :type username_mapping: dict[str, str] | None
    :return: A validated alters task API response object.
    :rtype: AltersTaskResponse
    """
    mapping = username_mapping or {}
    payload = task.model_dump()
    created_by = payload.get("created_by")
    payload["created_by"] = mapping.get(created_by, created_by)
    last_updated_by = payload.get("last_updated_by")
    payload["last_updated_by"] = mapping.get(last_updated_by, last_updated_by)
    meta = payload.get("data", {}).get("meta")
    if isinstance(meta, dict):
        command_line = _command_line_from_meta(meta)
        if command_line is not None:
            meta["_command_line"] = command_line
    return AltersTaskResponse(
        **payload,
        service_type=ServiceTypeEnum.MYSQL,
        status=status,
        connectivity_warning=connectivity_warning,
        pre_checks_auto_fire_warning=pre_checks_auto_fire_warning,
    )


async def get_alters_api_task_responses(
    tasks_api: TaskAPI,
    service_type: ServiceTypeEnum | None = None,
    status: TaskHistoryStatusEnum | None = None,
    username_mapping: dict[str, str] | None = None,
) -> list[AltersTaskResponse]:
    """Retrieve parent alters task responses for the JSON API.

    Satellite tasks (dry-run and pre-checks siblings) are excluded from the
    list — only parent execute tasks are returned.

    :param tasks_api: The TaskAPI instance used to query alters tasks.
    :type tasks_api: TaskAPI
    :param service_type: Optional service type filter for the alters task list.
    :type service_type: ServiceTypeEnum | None
    :param status: Optional latest-history status filter for the alters task list.
    :type status: TaskHistoryStatusEnum | None
    :param username_mapping: Optional mapping of user IDs to usernames.
    :type username_mapping: dict[str, str] | None
    :return: The alters task responses matching the requested filters.
    :rtype: list[AltersTaskResponse]
    """
    if service_type is not None and service_type != ServiceTypeEnum.MYSQL:
        return []

    params = {"owner": TaskOwner.ALTERS.value}
    response = await tasks_api.get("/", params=params)
    tasks = [
        Task.model_validate(task)
        for task in response["items"]
        if not task.get("data", {}).get("parent")
    ]
    task_status_pairs = [
        (task, await get_alters_task_status(task.name, tasks_api)) for task in tasks
    ]

    return [
        build_alters_api_task_response(
            task,
            status=task_status,
            username_mapping=username_mapping,
        )
        for task, task_status in task_status_pairs
        if status is None or task_status == status
    ]


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
