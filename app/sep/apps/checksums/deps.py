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

from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.checksums.models import ChecksumsCreate, ChecksumsForm, OWNER
from app.sep.apps.checksums.spec import build_checksums_arg_prefix
from app.sep.apps.framework import make_task_dep
from app.sep.apps.framework.form_dsl import make_arg_parser
from app.sep.apps.framework.spec import build_command_args
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
    get_created_entity,
    get_tasks_context,
    InventoryAPI,
    protected_task_guard,
    TaskAPI,
)
from app.sep.inventory import CreatedService
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskWrite,
)

logger = logging.getLogger(__name__)


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


def assemble_checksum_payload(
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

    The legacy Jinja form path's envelope builder. Builds the CLI argument string
    from the shared
    :func:`~app.sep.apps.checksums.spec.build_checksums_arg_prefix` plus the
    framework's declarative ``build_command_args`` (over a ``ChecksumsForm`` rebuilt
    from the resolved values) — the same pair the model-first JSON spec builder
    uses — and assembles the ``TaskWrite`` meta, so a form-created task's Nomad
    payload stays byte-identical to a JSON-created one.

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
    form = ChecksumsForm(
        task_name=task_name,
        hostname=hostname,
        service_id=service.id,
        recursion_method=recursion_method,
        dsn_table=dsn_table,
        databases=databases,
        tables=tables,
        pause_file=pause_file,
        binary_index=binary_index,
        explain_arg=explain_arg,
        fail_on_stopped_replication=fail_on_stopped_replication,
        truncate_replicate_table=truncate_replicate_table,
        progress=progress,
        set_vars=set_vars,
        max_load=max_load,
        chunk_time=chunk_time,
        max_lag=max_lag,
        alert_on_fail=alert_on_fail,
    )
    args = build_checksums_arg_prefix(
        service,
        recursion_method=recursion_method,
        dsn_table=dsn_table,
        extra_remaining_args=extra_remaining_args,
    ) + build_command_args(form)

    return TaskWrite(
        owner=OWNER,
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

    return assemble_checksum_payload(
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


get_checksums_task = make_task_dep(OWNER)

ChecksumsTask = Annotated[Task, Depends(get_checksums_task)]


get_unprotected_checksums_task = protected_task_guard(get_checksums_task)

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
        if history.get("task", {}).get("owner") == OWNER
    }


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
    "extra_args": "",
}

_CHECKSUMS_ARG_MAPPINGS = {
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

_CHECKSUMS_FLAG_MAPPINGS = {
    "--binary-index": "binary_index",
    "--explain": "explain_arg",
    "--fail-on-stopped-replication": "fail_on_stopped_replication",
    "--truncate-replicate-table": "truncate_replicate_table",
}

parse_checksums_task_args = make_arg_parser(
    defaults=_CHECKSUMS_DEFAULTS,
    arg_mappings=_CHECKSUMS_ARG_MAPPINGS,
    flag_mappings=_CHECKSUMS_FLAG_MAPPINGS,
    skip_leading_positional=True,
)


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
        OWNER,
        service_type=ServiceTypeEnum.MYSQL,
        alert_on_fail_default=True,
    )


ChecksumsIndexContext = Annotated[dict[str, Any], Depends(get_checksums_index_context)]
