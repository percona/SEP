"""Define dependencies for the Alters plugin."""

import logging
import re
import shlex
from typing import Annotated, Any

from fastapi import Depends, Form

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
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)


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
    dsn = f"D={schema.name},t={table.name}"
    if service.port is not None:
        dsn = f"P={service.port},{dsn}"

    if service.node.address != "localhost":
        dsn = f"h={service.node.address},{dsn}"

    if form.recursion_method == "dsn":
        form.recursion_method = f"dsn={form.dsn_table}"

    args = [
        f"--alter={form.alter}",
        dsn,
        f"--recursion-method={form.recursion_method}",
    ]

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
                "_schema_name": schema.name,
                "_table_name": table.name,
            },
        },
        name=form.task_name,
        target=form.hostname,
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
    meta = task["data"]["meta"]
    return {
        "hostname": meta["target"],
        "table": f"{meta['_schema_name']}.{meta['_table_name']}",
    }


async def get_alters_index_context(
    inventory_api: InventoryAPI, tasks_api: TaskAPI, context: DefaultContext
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
    :return: An updated context dictionary containing Alters-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api, tasks_api, get_alters_task_info, context, TaskOwner.ALTERS
    )


def parse_dsn(dsn_part: str) -> dict[str, str]:
    """Parse DSN parameters from a DSN string.

    :param dsn_part: A string containing DSN parameters.
    :return: A dictionary mapping DSN parameter keys to values.
    """
    pattern = r"(h=[^,\s]+)?(?:,)?(P=\d+)?(?:,)?(D=[^,\s]+)?(?:,)?(t=[^,\s]+)?"
    matches = re.findall(pattern, dsn_part)
    dsn_dict: dict[str, str] = {}
    for match in matches:
        for param in match:
            if param:
                key, value = param.split("=")
                dsn_dict[key] = value
    return dsn_dict


async def get_service_ids(
    inventory_api: Any, dsn_dict: dict[str, str]
) -> dict[str, str]:
    """Retrieve service, schema, and table IDs from the Inventory API.

    :param inventory_api: The Inventory API client.
    :param dsn_dict: Dictionary containing DSN parameters.
    :return: A dictionary with service_id, source_db_id, and source_table_id if available.
    """
    service_data: dict[str, str] = {}
    source_host = dsn_dict.get("h", "localhost")
    source_port = dsn_dict.get("P", "3306")
    if source_host and source_port:
        service_response = await inventory_api.get(
            "/services/id", params={"address": source_host, "port": source_port}
        )
        service_id = service_response["service_id"]
        service_data["service_id"] = service_id

        source_db = dsn_dict.get("D")
        if source_db and service_id:
            schema_response = await inventory_api.get(
                "/schemas/id", params={"name": source_db, "service_id": service_id}
            )
            schema_id = schema_response["schema_id"]
            service_data["source_db_id"] = schema_id

            source_table = dsn_dict.get("t")
            if source_table and schema_id:
                table_response = await inventory_api.get(
                    "/tables/id", params={"name": source_table, "schema_id": schema_id}
                )
                service_data["source_table_id"] = table_response["table_id"]
    return service_data


def parse_recursion_method(recursion_arg: str) -> tuple[str, str | None]:
    """Parse the recursion method argument.

    :param recursion_arg: A string argument for recursion.
    :return: A tuple containing the recursion method and an optional DSN table if applicable.
    :raises ValueError: If the recursion argument is not as expected.
    """
    match = re.match(r"--recursion-method=(.*)", recursion_arg)
    if not match:
        raise ValueError(
            f"Unexpected recursion arg (expected --recursion-method=...): {recursion_arg}"
        )
    recursion_method = match.group(1)
    dsn_table: str | None = None
    if recursion_method.startswith("dsn="):
        dsn_table = recursion_method.split("=", 1)[1]
        recursion_method = "dsn"
    return recursion_method, dsn_table


def parse_optional_arguments(args: list[str]) -> dict[str, Any]:
    """Process optional and flag arguments from a list of arguments.

    :param args: List of string arguments.
    :return: A dictionary containing parsed arguments.
    """
    alter_data: dict[str, Any] = {}
    optional_args_map = {
        "pause_file": r"--pause-file=(.*)",
        "new_table_name": r"--new-table-name=(.*)",
        "tries": r"--tries=(.*)",
        "set_vars": r"--set-vars=(.*)",
        "critical_load": r"--critical-load=(.*)",
        "max_load": r"--max-load=(.*)",
        "chunk_time": r"--chunk-time=(.*)",
        "max_lag": r"--max-lag=(.*)",
    }
    flag_args_map = {
        "print_arg": "--print",
        "no_swap_tables": "--no-swap-tables",
        "no_drop_old_table": "--no-drop-old-table",
        "no_drop_new_table": "--no-drop-new-table",
        "no_drop_triggers": "--no-drop-triggers",
    }

    for arg in args:
        matched = False
        # Check for optional arguments with a value
        for field_key, pattern in optional_args_map.items():
            m = re.match(pattern, arg)
            if m:
                alter_data[field_key] = m.group(1)
                matched = True
                break
        if matched:
            continue

        # Check for flag arguments
        for flag_key, flag_value in flag_args_map.items():
            if arg == flag_value:
                alter_data[flag_key] = True
                matched = True
                break
        if matched:
            continue

        # Check for progress argument
        if arg.startswith("--progress="):
            alter_data["progress"] = arg.split("=", 1)[1]
    return alter_data


async def get_alters_detail_context(
    task: AltersTask,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
) -> dict[str, Any]:
    """Assemble the context for the Alters detail view.

    This dependency extracts task details, retrieves associated service, schema,
    and table information, and also gathers history and stats data.

    :param task: The AltersTask instance resolved by the task name.
    :param inventory_api: The Inventory API client.
    :param tasks_api: The Tasks API client.
    :param context: The default context dictionary.
    :return: A dictionary containing all data needed for the detail view template.
    :rtype: dict[str, Any]
    """
    data = task.data
    task_config = data["TaskGroups"][0]["Tasks"][0]["Config"]

    # Begin building alter_data
    alter_data: dict[str, Any] = {"task_name": task.name}
    args: list[str] = task_config.get("args", [])

    # Parse the alter argument
    alter_arg = args[0]
    match = re.match(r"--alter=(.*)", alter_arg)
    if not match:
        raise ValueError(f"Unexpected first arg (expected --alter=...): {alter_arg}")
    alter_data["alter"] = match.group(1)

    # Parse DSN part and retrieve service/schema/table IDs
    dsn_part = args[1]
    dsn_dict = parse_dsn(dsn_part)
    service_data = await get_service_ids(inventory_api, dsn_dict)
    alter_data.update(service_data)

    # Parse recursion argument
    recursion_arg = args[2]
    recursion_method, dsn_table = parse_recursion_method(recursion_arg)
    alter_data["recursion_method"] = recursion_method
    if dsn_table:
        alter_data["dsn_table"] = dsn_table

    # Process remaining optional and flag arguments
    optional_args = args[3:]
    alter_data.update(parse_optional_arguments(optional_args))

    # Build task meta data for the context
    meta = data["TaskGroups"][0]["Tasks"][0]["Meta"]
    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "hostname": data["Constraints"][0]["RTarget"],
        "table": f"{meta['schema_name']}.{meta['table_name']}",
        "cmd": f"{task_config['command']} {' '.join(task_config['args'])}",
        "meta": meta,
    }
    context["task"] = task_data

    # Fetch history, running tasks, and stats
    context["history"] = await tasks_api.get(f"/{task.name}/history/")
    context["running_tasks"] = await tasks_api.get(
        f"/{task.name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")
    context["alter_data"] = alter_data

    # Retrieve executor hosts and MySQL services with their schemas
    executor_hosts = await tasks_api.get("/hosts/")
    mysql_services = await inventory_api.get(
        "/services/",
        params={"service_type": ServiceTypeEnum.MYSQL},
    )
    for service in mysql_services:
        service["schemas"] = await inventory_api.get(
            f"/services/{service['id']}/schemas/"
        )
    context["executor_hosts"] = list(executor_hosts.values())
    context["mysql_services"] = mysql_services

    return context
