"""Define dependencies for the Alters plugin."""

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
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import GeneratedTask, Task, TaskBackendEnum, TaskOwner, TaskWrite

logger = logging.getLogger(__name__)


async def build_alters_task_payload(
    form: Annotated[AltersCreate, Form()],
    inventory_api: InventoryAPI,
) -> GeneratedTask:
    """Build the alter task payload from form.

    Build the payload for an Alters task to be executed, including the
    necessary command arguments for performing schema changes.

    :param form: The form data for the Alters creation.
    :type form: AltersCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    :return: A fully constructed `GeneratedTask` object containing all the necessary
        commands and parameters for the Alters task execution.
    :rtype: GeneratedTask
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
        "parent": meta.get("parent"),
    }


def extract_service_info(meta: dict[str, Any]) -> tuple[str, int]:
    """Extract service host and port from task configuration arguments.

    Parses the task arguments to extract the service host and port from DSN-like
    connection strings. Defaults to localhost:3306 if not specified.

    :param meta: The task meta containing the args string.
    :type meta: dict[str, Any]
    :return: A tuple containing (service_host, service_port).
    :rtype: tuple[str, int]
    """
    service_host = "localhost"
    service_port = 3306

    args_string = meta.get("args", "")
    args = shlex.split(args_string)

    for task_arg in args:
        if "=" in task_arg and not task_arg.startswith("--"):
            for param in task_arg.split(","):
                if "=" in param:
                    key, value = param.split("=", 1)
                    if key == "h":
                        service_host = value
                    elif key == "P":
                        service_port = int(value)

    return service_host, service_port


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
            form_values["dsn_table"] = recursion_method.split("=", 1)[1]
        else:
            form_values["recursion_method"] = recursion_method
        return

    if arg.startswith("--progress="):
        form_values["progress"] = arg.split("=", 1)[1]
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
    }

    args_string = meta.get("args", "")
    args = shlex.split(args_string)

    for arg in args:
        parse_single_arg(arg, form_values)

    return form_values


async def get_alters_index_context(
    request: Request,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
) -> dict[str, Any]:
    """Assemble the context for the Alters plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param request: The HTTP request object.
    :type request: Request
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
        request,
        inventory_api,
        tasks_api,
        get_alters_task_info,
        context,
        TaskOwner.ALTERS,
        alert_on_fail_default=True,
    )
