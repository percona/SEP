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
from app.sep.apps.checksums.models import (
    ChecksumsCreate,
    ChecksumsForm,
    coerce_target_list,
    OWNER,
)
from app.sep.apps.checksums.spec import (
    build_checksums_arg_prefix,
    build_checksums_command_args,
    build_checksums_spec,
    resolve_checksums_target_args,
)
from app.sep.apps.framework import make_task_dep
from app.sep.apps.framework.form_dsl import (
    derive_arg_parser_from_model,
    make_arg_parser,
)
from app.sep.apps.framework.spec import (
    assemble_envelope,
    resolve_refs,
    stamp_form_input,
)
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


def legacy_checksums_create_to_form(
    flat: ChecksumsCreate,
) -> tuple[ChecksumsForm, list[str]]:
    """Map legacy Jinja form POST data to a validated :class:`ChecksumsForm`.

    Merges comma-separated ``databases`` / ``tables`` fields, legacy inventory
    ``schema_id`` / ``table_id`` selections, and ``--databases`` / ``--tables``
    tokens from ``extra_args`` into the model-first target lists. Returns the
    validated form and any remaining CLI tokens for the legacy path's
    ``extra_remaining_args`` thread-through.

    :param flat: The legacy HTML form body.
    :return: ``(form, remaining_args)`` where ``remaining_args`` excludes target
        ``--databases`` / ``--tables`` tokens.
    """
    databases = list(coerce_target_list(flat.databases))
    tables = list(coerce_target_list(flat.tables))

    if flat.schema_id and -1 not in flat.schema_id:
        databases.extend(schema_id for schema_id in flat.schema_id if schema_id > 0)

    if flat.table_id:
        tables.extend(tid for tid in flat.table_id if tid > 0)

    remaining_args = []
    if flat.extra_args:
        for arg in shlex.split(flat.extra_args):
            if arg.startswith("--databases="):
                databases.extend(coerce_target_list(arg.split("=", 1)[1]))
            elif arg.startswith("--tables="):
                tables.extend(coerce_target_list(arg.split("=", 1)[1]))
            else:
                remaining_args.append(arg)

    form = ChecksumsForm.model_validate(
        {
            **flat.model_dump(
                exclude={"schema_id", "table_id", "extra_args", "databases", "tables"}
            ),
            "databases": databases,
            "tables": tables,
        }
    )
    return form, remaining_args


def assemble_checksum_payload(
    service: CreatedService,
    form: ChecksumsForm,
    *,
    databases_arg: str,
    tables_arg: str,
    extra_remaining_args: Iterable[str] = (),
) -> TaskWrite:
    """Assemble a TaskWrite for pt-table-checksum from a validated form.

    The legacy Jinja form path's envelope builder. Builds the CLI argument string
    from the shared
    :func:`~app.sep.apps.checksums.spec.build_checksums_arg_prefix` plus
    :func:`~app.sep.apps.checksums.spec.build_checksums_command_args` — the same
    pair the model-first JSON path uses — and assembles the ``TaskWrite`` meta, so
    a form-created task's Nomad payload stays byte-identical to a JSON-created one.

    :param service: The validated inventory service instance.
    :param form: The validated checksums create form.
    :param databases_arg: Comma-separated database names (pre-resolved).
    :param tables_arg: Comma-separated ``schema.table`` strings (pre-resolved).
    :param extra_remaining_args: Additional pre-parsed CLI args (form path only).
    :return: A fully constructed ``TaskWrite`` object.
    """
    args = build_checksums_arg_prefix(
        service,
        recursion_method=form.recursion_method,
        dsn_table=form.dsn_table,
        extra_remaining_args=extra_remaining_args,
    ) + build_checksums_command_args(
        form,
        databases_arg=databases_arg,
        tables_arg=tables_arg,
    )

    return TaskWrite(
        owner=OWNER,
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
                CONNECTIVITY_META_HOST_KEY: service.node.address,
                CONNECTIVITY_META_PORT_KEY: service.port or DEFAULT_MYSQL_PORT,
                CONNECTIVITY_META_SERVICE_TYPE_KEY: service.type.value,
            },
        },
        name=form.task_name,
        target=form.hostname,
        alert_on_fail=form.alert_on_fail,
    )


async def build_checksums_payload(
    form: ChecksumsForm,
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build a checksums ``TaskWrite`` from the model-first create form.

    Resolve reference fields and multi-value schema/table targets, assemble the
    run-command spec, and stamp the validated form body under ``data['_form']``.

    :param form: The validated checksums create form.
    :param inventory_api: The inventory API client.
    :return: A fully constructed ``TaskWrite`` object.
    """
    resolved = await resolve_refs(form, inventory_api)
    databases_arg, tables_arg = await resolve_checksums_target_args(form, inventory_api)
    spec = build_checksums_spec(
        form,
        resolved,
        databases_arg=databases_arg,
        tables_arg=tables_arg,
    )
    write = assemble_envelope(
        spec,
        resolved,
        name=form.task_name,
        owner=OWNER,
        alert_on_fail=form.alert_on_fail,
    )
    stamp_form_input(write, form)
    return write


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
    checksums_form, remaining_args = legacy_checksums_create_to_form(form)
    databases_arg, tables_arg = await resolve_checksums_target_args(
        checksums_form, inventory_api
    )

    return assemble_checksum_payload(
        service,
        checksums_form,
        databases_arg=databases_arg,
        tables_arg=tables_arg,
        extra_remaining_args=remaining_args,
    )


ChecksumsGeneratedTask = Annotated[TaskWrite, Depends(build_checksums_task_payload)]


get_checksums_task = make_task_dep(OWNER)

ChecksumsTask = Annotated[Task, Depends(get_checksums_task)]


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

_CHECKSUMS_ARG_MAPPINGS, _CHECKSUMS_FLAG_MAPPINGS = derive_arg_parser_from_model(
    ChecksumsForm,
    extra_arg_mappings={
        "--recursion-method=": "recursion_method",
        "--databases=": "databases",
        "--tables=": "tables",
    },
)

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
