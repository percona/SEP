"""Define dependencies for the Alters plugin."""

import logging
from typing import Annotated

from fastapi import Depends
from fastapi import Form
from fastapi import HTTPException

from app.sep.deps import TaskAPI
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import GeneratedTask

logger = logging.getLogger(__name__)


async def build_alters_task_payload(
    form: Annotated[AltersCreate, Form()],
) -> GeneratedTask:
    """Build the alter task payload from form.

    Build the payload for an Alters task to be executed, including the
    necessary command arguments for performing schema changes.

    :param form: The form data for the Alters creation.
    :type form: AltersCreate
    :return: A fully constructed `GeneratedTask` object containing all the necessary
        commands and parameters for the Alters task execution.
    :rtype: GeneratedTask
    """
    # TODO: port from Service
    if form.connect_to == "localhost":
        dsn = f"D={form.schema_name},t={form.table_name}"
    else:
        dsn = f"h={form.connect_to},D={form.schema_name},t={form.table_name}"

    if form.recursion_method == "dsn":
        form.recursion_method = f"dsn={form.dsn_table}"

    args = [
        f"--alter={form.alter}",
        dsn,
        f"--recursion-method={form.recursion_method}",
    ]

    # Mapping form fields to their respective arguments
    optional_args = {
        'pause_file': f'--pause-file={form.pause_file}',
        'new_table_name': f'--new-table-name={form.new_table_name}',
        'tries': f'--tries={form.tries}',
        'set_vars': f'--set-vars={form.set_vars}',
        'critical_load': f'--critical-load={form.critical_load}',
        'max_load': f'--max-load={form.max_load}',
        'chunk_time': f'--chunk-time={form.chunk_time}',
        'max_lag': f'--max-lag={form.max_lag}',
    }

    # Adding optional arguments if their values exist
    args.extend(arg for key, arg in optional_args.items() if getattr(form, key))

    # Adding flag arguments (no value needed, just presence)
    flag_args = {
        'print_arg': '--print',
        'no_swap_tables': '--no-swap-tables',
        'no_drop_old_table': '--no-drop-old-table',
        'no_drop_new_table': '--no-drop-new-table',
        'no_drop_triggers': '--no-drop-triggers',
    }

    # Adding flag arguments if set to True
    args.extend(arg for key, arg in flag_args.items() if getattr(form, key))

    # Adding '--progress' argument if 'print_arg' is set
    if form.print_arg:
        args.append(f'--progress={form.progress}')

    return GeneratedTask(
        app="alters",
        commands=[
            {
                "args": [*args, "--execute"],
                "command": "pt-online-schema-change",
                "meta": {
                    "schema_name": form.schema_name,
                    "table_name": form.table_name,
                },
            },
        ],
        name=form.task_name,
        target=form.hostname,
    )


AltersGeneratedTask = Annotated[GeneratedTask, Depends(build_alters_task_payload)]


async def get_alters_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> dict:  # TODO: refactor - (ab)use pydantic models
    """Fetch and validate a task for the Alters plugin.

    This function retrieves a task by its name from the Tasks API and validates
    that it is owned by the Alters plugin. If the task does not exist or is not
    owned by Alters, it raises a 404 HTTP exception.

    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :type tasks_api: TaskAPI
    :return: The task data as a dictionary.
    :rtype: dict[str, Any]
    :raises HTTPException: If the task is not found or is not owned by Alters
        (HTTP status 404).
    """
    task = await tasks_api.get(
        f"/{task_name}",
    )  # TODO: refactor - (ab)use pydantic models
    if (
        task.get("owner") != "alters"
    ):  # TODO: Consider getting owner name from plugin MODULE_NAME
        raise HTTPException(404)
    return task


AltersTask = Annotated[dict, Depends(get_alters_task)]
