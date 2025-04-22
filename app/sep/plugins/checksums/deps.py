"""Define dependencies for the Checksums plugin."""

import logging
import shlex
from typing import Annotated, Any

from fastapi import Depends, Form, Request

from app.inventory.models import ServiceTypeEnum
from app.sep.deps import (
    DefaultContext,
    get_created_entity,
    get_task_by_name,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.checksums.models import ChecksumsCreate
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)


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

    # --databases and --tables options
    databases = ""
    if form.schema_id is not None and len(form.schema_id) > 0:
        for s in form.schema_id:
            schema = await get_created_entity(
                inventory_api,
                SyncInventoryEntityTypeEnum.SCHEMA,
                s,
                service_id=service.id,
            )
            databases += f"{schema.name},"
    form.databases = databases.rstrip(",")

    tables = ""
    if (
        form.schema_id is not None
        and len(form.schema_id) == 1
        and form.table_id is not None
    ):
        for t in form.table_id:
            table = await get_created_entity(
                inventory_api,
                SyncInventoryEntityTypeEnum.TABLE,
                t,
                schema_id=next(iter(form.schema_id)),
            )
            tables += f"{table.name},"
    form.tables = tables.rstrip(",")

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
    args.append("--execute")

    return TaskWrite(
        owner=TaskOwner.ALTERS,
        backend=TaskBackendEnum.PROXY,
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-table-checksum",
                "args": shlex.join(args),
                "target": form.hostname,
                "_service_name": service.name,
            },
        },
        name=form.task_name,
        target=form.hostname,
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
    meta = task["data"]["meta"]
    service_name = ""
    if "service_name" in meta:
        service_name = meta["_service_name"]
    return {
        "hostname": meta["target"],
        "service_name": f"{service_name}",
    }


async def get_checksums_index_context(
    request: Request,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
) -> dict[str, Any]:
    """Assemble the context for the Checksums plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param request: The HTTP request object.
    :type request: Request
    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Checksums-specific information.
    :type context: DefaultContext
    :return: An updated context dictionary containing Checksums-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        request,
        inventory_api,
        tasks_api,
        get_checksums_task_info,
        context,
        TaskOwner.CHECKSUMS,
    )
