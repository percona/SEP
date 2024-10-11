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
    if form.connect_to == "localhost":
        dsn = f"D={form.schema_name},t={form.table_name}"
    else:
        dsn = f"h={form.connect_to},D={form.schema_name},t={form.table_name}"

    if form.recursion_method == "dsn":
        form.recursion_method = f"dsn={form.dsn_table}"

    return GeneratedTask(
        app="alters",
        commands=[
            {
                "args": [
                    f"--alter={form.alter}",
                    dsn,
                    f"--recursion-method={form.recursion_method}",
                    "--execute",
                ],
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
