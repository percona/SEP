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
import shlex
from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import Depends, Form

from app.core.exceptions import HTTPConflictException
from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.deps import (
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
from app.sep.plugins.checksums.models import (
    ChecksumsCreate,
    ChecksumTaskResponse,
    ChecksumTaskWrite,
)
from app.sep.plugins.framework import ConnectivityWarning, extract_latest_task_status
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)

DEFAULT_RECURSION_DSN_TABLE = "D=percona,t=dsns"


def extract_databases_and_tables_from_extra_args(form: ChecksumsCreate) -> list[str]:
    """Extract --databases and --tables from extra_args and add to form fields.

    :param form: The form data for the Checksums creation.
    :type form: ChecksumsCreate
    :return: List of remaining arguments (excluding --databases and --tables).
    :rtype: list[str]
    """
    if not form.extra_args:
        return []

    remaining_args = []
    for arg in shlex.split(form.extra_args):
        if arg.startswith("--databases="):
            value = arg.split("=", 1)[1]
            form.databases = form.databases + "," + value if form.databases else value
        elif arg.startswith("--tables="):
            value = arg.split("=", 1)[1]
            form.tables = form.tables + "," + value if form.tables else value
        else:
            remaining_args.append(arg)

    return remaining_args


async def process_schema_and_table_ids(
    form: ChecksumsCreate, inventory_api: InventoryAPI
) -> None:
    """Process schema_id and table_id to set databases and tables form fields.

    :param form: The form data for the Checksums creation.
    :type form: ChecksumsCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    """
    if not form.schema_id or len(form.schema_id) == 0:
        return

    if -1 in form.schema_id:
        return

    database_names = []
    for schema_id in form.schema_id:
        schema = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SCHEMA,
            schema_id,
        )
        database_names.append(schema.name)

    form.databases = ",".join(database_names)

    if form.table_id and len(form.table_id) > 0:
        table_entries = []
        valid_table_ids = [t for t in form.table_id if t > 0]

        for table_id in valid_table_ids:
            table = await get_created_entity(
                inventory_api,
                SyncInventoryEntityTypeEnum.TABLE,
                table_id,
            )
            table_schema = None
            for schema_id in form.schema_id:
                schema = await get_created_entity(
                    inventory_api,
                    SyncInventoryEntityTypeEnum.SCHEMA,
                    schema_id,
                )
                if schema.id == table.schema_id:
                    table_schema = schema
                    break

            if table_schema:
                table_entries.append(f"{table_schema.name}.{table.name}")

        form.tables = ",".join(table_entries)


def _assemble_checksum_payload(
    service: CreatedService,
    *,
    task_name: str,
    hostname: str,
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
    alert_on_fail: bool,
    extra_remaining_args: Iterable[str] = (),
) -> TaskWrite:
    """Assemble a TaskWrite for pt-table-checksum from pre-resolved inputs.

    Owns DSN construction, ``--recursion-method=dsn=…`` expansion (on a local
    copy — never mutates caller arguments), optional/flag arg mapping, and
    ``TaskWrite`` meta assembly. Both the form-based and JSON paths delegate
    here so Nomad payloads are byte-identical regardless of the call origin.

    :param service: The validated inventory service instance.
    :type service: CreatedService
    :param task_name: The task name.
    :type task_name: str
    :param hostname: The executor host.
    :type hostname: str
    :param recursion_method: The replica-discovery method (e.g. ``"processlist"``).
    :type recursion_method: str
    :param dsn_table: DSN table used when ``recursion_method == "dsn"``.
    :type dsn_table: str
    :param databases: Comma-separated database names (pre-resolved).
    :type databases: str
    :param tables: Comma-separated ``schema.table`` strings (pre-resolved).
    :type tables: str
    :param pause_file: Pause-file path.
    :type pause_file: str
    :param binary_index: Enable ``--binary-index`` flag.
    :type binary_index: bool
    :param explain_arg: Enable ``--explain`` flag.
    :type explain_arg: bool
    :param fail_on_stopped_replication: Enable ``--fail-on-stopped-replication``.
    :type fail_on_stopped_replication: bool
    :param truncate_replicate_table: Enable ``--truncate-replicate-table``.
    :type truncate_replicate_table: bool
    :param progress: ``--progress`` value.
    :type progress: str
    :param set_vars: ``--set-vars`` value.
    :type set_vars: str
    :param max_load: ``--max-load`` value.
    :type max_load: str
    :param chunk_time: ``--chunk-time`` value.
    :type chunk_time: str
    :param max_lag: ``--max-lag`` value.
    :type max_lag: str
    :param alert_on_fail: Whether to alert on task failure.
    :type alert_on_fail: bool
    :param extra_remaining_args: Additional pre-parsed CLI args (form path only).
    :type extra_remaining_args: Iterable[str]
    :return: A fully constructed ``TaskWrite`` object.
    :rtype: TaskWrite
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

    return TaskWrite(
        owner=TaskOwner.CHECKSUMS,
        backend=TaskBackendEnum.PROXY,
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-table-checksum",
                "args": shlex.join(args),
                "target": hostname,
                "_service_name": service.name,
                "_service_host": service.node.address,
                "_service_port": service.port,
                CONNECTIVITY_META_HOST_KEY: service.node.address,
                CONNECTIVITY_META_PORT_KEY: service.port or DEFAULT_MYSQL_PORT,
                CONNECTIVITY_META_SERVICE_TYPE_KEY: service.type.value,
            },
        },
        name=task_name,
        target=hostname,
        alert_on_fail=alert_on_fail,
    )


async def build_checksums_task_payload(
    form: Annotated[ChecksumsCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the checksums task payload from form.

    Build the payload for an Checksums task to be executed, including the
    necessary command arguments.

    :param form: The form data for the Checksums creation.
    :type form: ChecksumsCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    :return: A fully constructed ``TaskWrite`` object containing all the necessary
        commands and parameters for the Checksums task execution.
    :rtype: TaskWrite
    """
    service = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        form.service_id,
        type=ServiceTypeEnum.MYSQL,
    )
    await process_schema_and_table_ids(form, inventory_api)
    remaining_args = extract_databases_and_tables_from_extra_args(form)

    return _assemble_checksum_payload(
        service,
        task_name=form.task_name,
        hostname=form.hostname,
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
        alert_on_fail=form.alert_on_fail,
        extra_remaining_args=remaining_args,
    )


ChecksumsGeneratedTask = Annotated[TaskWrite, Depends(build_checksums_task_payload)]


async def build_checksum_task(
    body: ChecksumTaskWrite,
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the checksums task payload from a JSON request body.

    JSON-path counterpart to :func:`build_checksums_task_payload`. Accepts
    pre-resolved ``databases`` and ``tables`` strings — no schema/table ID
    resolution or ``extra_args`` parsing.

    :param body: The validated JSON request body.
    :type body: ChecksumTaskWrite
    :param inventory_api: The Inventory API client.
    :type inventory_api: InventoryAPI
    :return: A fully constructed ``TaskWrite`` object.
    :rtype: TaskWrite
    """
    service = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        body.service_id,
        type=ServiceTypeEnum.MYSQL,
    )
    return _assemble_checksum_payload(
        service,
        task_name=body.task_name,
        hostname=body.hostname,
        recursion_method=body.recursion_method,
        dsn_table=body.dsn_table,
        databases=body.databases,
        tables=body.tables,
        pause_file=body.pause_file,
        binary_index=body.binary_index,
        explain_arg=body.explain_arg,
        fail_on_stopped_replication=body.fail_on_stopped_replication,
        truncate_replicate_table=body.truncate_replicate_table,
        progress=body.progress,
        set_vars=body.set_vars,
        max_load=body.max_load,
        chunk_time=body.chunk_time,
        max_lag=body.max_lag,
        alert_on_fail=body.alert_on_fail,
    )


async def get_checksums_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Fetch and validate a task for the Checksums plugin.

    This function retrieves a task by its name from the Tasks API and validates
    that it is owned by the Checksums plugin. If the task does not exist or is not
    owned by Checksums, it raises a 404 HTTP exception.

    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :type tasks_api: TaskAPI
    :return: The retrieved task.
    :rtype: Task
    :raises HTTPNotFoundException: If the task is not found or is not owned by Checksums.
    """
    return await get_task_by_name(tasks_api, task_name, TaskOwner.CHECKSUMS)


ChecksumsTask = Annotated[Task, Depends(get_checksums_task)]


async def get_unprotected_checksums_task(task: ChecksumsTask) -> Task:
    """Return a checksums task or raise 409 when the task is protected.

    :param task: The checksums task resolved from the path parameter.
    :type task: ChecksumsTask
    :raises HTTPConflictException: If the task is marked as protected.
    """
    if task.protected:
        raise HTTPConflictException("Cannot edit a protected task.")
    return task


UnprotectedChecksumsTask = Annotated[Task, Depends(get_unprotected_checksums_task)]


async def get_checksums_task_names_by_status(
    tasks_api: TaskAPI,
    status: TaskHistoryStatusEnum,
) -> set[str]:
    """Retrieve checksum task names that have histories with the requested status.

    :param tasks_api: The TaskAPI instance used to query task histories.
    :type tasks_api: TaskAPI
    :param status: The status used to filter checksum task histories.
    :type status: TaskHistoryStatusEnum
    :return: The set of checksum task names that have at least one matching history.
    :rtype: set[str]
    """
    response = await tasks_api.get("/history/", params={"status": status})
    histories = response["items"]
    return {
        history["task"]["name"]
        for history in histories
        if history.get("task", {}).get("owner") == TaskOwner.CHECKSUMS.value
    }


async def get_checksums_task_status(
    task_name: str,
    tasks_api: TaskAPI,
) -> TaskHistoryStatusEnum | None:
    """Fetch the latest execution status for a checksum task.

    :param task_name: The name of the checksum task.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to query task history.
    :type tasks_api: TaskAPI
    :return: The latest known task status, or ``None`` if no history exists.
    :rtype: TaskHistoryStatusEnum | None
    """
    response = await tasks_api.get(f"/{task_name}/history/")
    return extract_latest_task_status(response["items"])


def build_checksums_api_task_response(
    task: Task,
    status: TaskHistoryStatusEnum | None = None,
    *,
    connectivity_warning: ConnectivityWarning | None = None,
    username_mapping: dict[str, str] | None = None,
) -> ChecksumTaskResponse:
    """Build a checksum task response object for the JSON API.

    :param task: The checksum task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :param connectivity_warning: A warning to surface when a connectivity
        check failed during the task creation flow.
    :type connectivity_warning: ConnectivityWarning | None
    :param username_mapping: Optional mapping of user IDs to usernames.
    :type username_mapping: dict[str, str] | None
    :return: A validated checksum task API response object.
    :rtype: ChecksumTaskResponse
    """
    mapping = username_mapping or {}
    task_data = task.model_dump()
    created_by = task_data.get("created_by")
    task_data["created_by"] = mapping.get(created_by, created_by)
    last_updated_by = task_data.get("last_updated_by")
    task_data["last_updated_by"] = mapping.get(last_updated_by, last_updated_by)
    return ChecksumTaskResponse(
        **task_data,
        service_type=ServiceTypeEnum.MYSQL,
        status=status,
        connectivity_warning=connectivity_warning,
    )


async def get_checksums_api_task_responses(
    tasks_api: TaskAPI,
    service_type: ServiceTypeEnum | None = None,
    status: TaskHistoryStatusEnum | None = None,
    username_mapping: dict[str, str] | None = None,
) -> list[ChecksumTaskResponse]:
    """Retrieve checksum task responses for the JSON API.

    :param tasks_api: The TaskAPI instance used to query checksum tasks.
    :type tasks_api: TaskAPI
    :param service_type: Optional service type filter for the checksum task list.
    :type service_type: ServiceTypeEnum | None
    :param status: Optional latest-history status filter for the checksum task list.
    :type status: TaskHistoryStatusEnum | None
    :param username_mapping: Optional mapping of user IDs to usernames.
    :type username_mapping: dict[str, str] | None
    :return: The checksum task responses matching the requested filters.
    :rtype: list[ChecksumTaskResponse]
    """
    if service_type is not None and service_type != ServiceTypeEnum.MYSQL:
        return []

    params = {"owner": TaskOwner.CHECKSUMS.value}
    response = await tasks_api.get("/", params=params)
    tasks = [Task.model_validate(task) for task in response["items"]]
    task_status_pairs = [
        (task, await get_checksums_task_status(task.name, tasks_api)) for task in tasks
    ]

    return [
        build_checksums_api_task_response(
            task, status=task_status, username_mapping=username_mapping
        )
        for task, task_status in task_status_pairs
        if status is None or task_status == status
    ]


def get_checksums_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Checksums plugin.

    Processes the task data to extract hostname and service name information.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing hostname and table information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    service_name = ""
    if "_service_name" in meta:
        service_name = meta["_service_name"]
    return {
        "hostname": meta["target"],
        "service_name": f"{service_name}",
        "created_by": task.get("created_by"),
        "last_updated_by": task.get("last_updated_by"),
    }


def parse_single_checksums_arg(arg: str, form_values: dict[str, Any]) -> None:
    """Parse a single checksums argument and update form values.

    :param arg: The argument to parse.
    :type arg: str
    :param form_values: The form values dictionary to update.
    :type form_values: dict[str, Any]
    """
    arg_mappings = {
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

    for arg_pattern, field_name in arg_mappings.items():
        if arg.startswith(arg_pattern):
            form_values[field_name] = arg.split("=", 1)[1]
            return

    flag_mappings = {
        "--binary-index": "binary_index",
        "--explain": "explain_arg",
        "--fail-on-stopped-replication": "fail_on_stopped_replication",
        "--truncate-replicate-table": "truncate_replicate_table",
    }

    for flag, field_name in flag_mappings.items():
        if arg == flag:
            form_values[field_name] = True
            return


def parse_checksums_task_args(meta: dict[str, Any]) -> dict[str, Any]:
    """Parse existing task arguments back into form field values.

    Extracts form field values from the task configuration arguments for editing.

    :param meta: The task meta containing the args string.
    :type meta: dict[str, Any]
    :return: A dictionary containing form field values.
    :rtype: dict[str, Any]
    """
    form_values = {
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
        "extra_args": "",
    }

    args_string = meta.get("args", "")
    args = shlex.split(args_string)

    # Skip the first argument (DSN)
    if args:
        args = args[1:]

    for arg in args:
        parse_single_checksums_arg(arg, form_values)

    return form_values


def extract_service_info(meta: dict[str, Any]) -> dict[str, Any]:
    """Extract service information from task meta.

    :param meta: The task meta data.
    :type meta: dict[str, Any]
    :return: A dictionary containing service information.
    :rtype: dict[str, Any]
    """
    return {
        "service_host": meta.get("_service_host", ""),
        "service_port": meta.get("_service_port", ""),
        "service_name": meta.get("_service_name", ""),
    }


async def get_checksums_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> dict[str, Any]:
    """Assemble the context for the Checksums plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Checksums-specific information.
    :type context: DefaultContext
    :param executor_hosts_ctx: The executor hosts context for the Checksums tasks.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: An updated context dictionary containing Checksums-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_checksums_task_info,
        executor_hosts_ctx,
        context,
        TaskOwner.CHECKSUMS,
        alert_on_fail_default=True,
    )
