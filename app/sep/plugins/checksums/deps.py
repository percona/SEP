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
from app.sep.plugins.checksums.models import ChecksumsCreate
from app.tasks.models import Task, TaskBackendEnum, TaskOwner, TaskWrite

logger = logging.getLogger(__name__)


def extract_databases_and_tables_from_extra_args(form: ChecksumsCreate) -> list[str]:
    """Extract --databases and --tables from extra_args and add to form fields.

    :param form: The form data for the Checksums creation.
    :return: List of remaining arguments (excluding --databases and --tables).
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
    :param inventory_api: The Inventory API to get entities from.
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
    :return: A fully constructed `TaskWrite` object containing all the necessary
        commands and parameters for the Checksums task execution.
    :rtype: TaskWrite
    """
    service = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        form.service_id,
        type=ServiceTypeEnum.MYSQL,
    )
    dsn = ""
    if service.port is not None:
        dsn = f"P={service.port},{dsn}"
    if service.node.address != "localhost":
        dsn = f"h={service.node.address},{dsn}"

    if form.recursion_method == "dsn":
        stripped_dsn = dsn.rstrip(",")
        form.recursion_method = f"dsn={stripped_dsn},{form.dsn_table}"

    args = [dsn]

    if form.recursion_method is not None and len(form.recursion_method) > 0:
        args.append(f"--recursion-method={form.recursion_method}")

    await process_schema_and_table_ids(form, inventory_api)

    remaining_args = extract_databases_and_tables_from_extra_args(form)
    args.extend(remaining_args)

    # Mapping form fields to their respective arguments
    optional_args = {
        "databases": f"--databases={form.databases}",
        "tables": f"--tables={form.tables}",
        "pause_file": f"--pause-file={form.pause_file}",
        "set_vars": f"--set-vars={form.set_vars}",
        "max_load": f"--max-load={form.max_load}",
        "chunk_time": f"--chunk-time={form.chunk_time}",
        "max_lag": f"--max-lag={form.max_lag}",
        "progress": f"--progress={form.progress}",
    }

    # Adding optional arguments if their values exist
    args.extend(arg for key, arg in optional_args.items() if getattr(form, key))

    # Adding flag arguments (no value needed, just presence)
    flag_args = {
        "binary_index": "--binary-index",
        "explain_arg": "--explain",
        "fail_on_stopped_replication": "--fail-on-stopped-replication",
        "truncate_replicate_table": "--truncate-replicate-table",
    }

    # Adding flag arguments if set to True
    args.extend(arg for key, arg in flag_args.items() if getattr(form, key))

    return TaskWrite(
        owner=TaskOwner.CHECKSUMS,
        backend=TaskBackendEnum.PROXY,
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-table-checksum",
                "args": shlex.join(args),
                "target": form.hostname,
                "_service_name": service.name,
                "_service_host": service.node.address,
                "_service_port": service.port,
            },
        },
        name=form.task_name,
        target=form.hostname,
        alert_on_fail=form.alert_on_fail,
    )


ChecksumsGeneratedTask = Annotated[TaskWrite, Depends(build_checksums_task_payload)]


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
