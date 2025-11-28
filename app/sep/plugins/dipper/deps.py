"""Define dependencies for the Skeleton plugin."""

import logging
from typing import Annotated, Any

from fastapi import Depends, Form

from app.sep.deps import (
    DefaultContext,
    ExecutorHosts,
    get_task_by_name,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.sep.plugins.skeleton.models import FormCreate
from app.tasks.models import Task, TaskBackendEnum, TaskOwner, TaskWrite

logger = logging.getLogger(__name__)


async def build_app_task_payload(
    form: Annotated[FormCreate, Form()],
) -> TaskWrite:
    """Build the task payload from form.

    Build the payload for a Dipper task to be executed, including the
    necessary command arguments.

    :param form: The form data for the Dipper creation.
    :type form: FormCreate
    :return: A fully constructed `TaskWrite` object containing all the necessary
        commands and parameters for the Dipper task execution.
    :rtype: TaskWrite
    """
    # TODO: Customize this function to build your task payload
    # This is a minimal example - adjust based on your plugin's needs
    return TaskWrite(
        owner=TaskOwner.ANY,  # TODO: Add your TaskOwner enum value to app/tasks/models.py
        backend=TaskBackendEnum.PROXY,
        data={
            "task": "run-command",
            "meta": {
                "command": "echo",  # TODO: Replace with your actual command
                "args": f"Hello from {form.task_name}",
                "target": form.hostname,
            },
        },
        name=form.task_name,
        target=form.hostname,
        alert_on_fail=form.alert_on_fail,
    )


AppGeneratedTask = Annotated[TaskWrite, Depends(build_app_task_payload)]


async def get_app_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Fetch and validate a task for the Dipper plugin.

    This function retrieves a task by its name from the Tasks API and validates
    that it is owned by the Dipper plugin. If the task does not exist or is not
    owned by Dipper, it raises a 404 HTTP exception.

    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :type tasks_api: TaskAPI
    :return: The retrieved task.
    :rtype: Task
    :raises HTTPNotFoundException: If the task is not found or is not owned by Dipper.
    """
    # TODO: Replace TaskOwner.ANY with your TaskOwner enum value once added
    return await get_task_by_name(tasks_api, task_name, TaskOwner.ANY)


AppTask = Annotated[Task, Depends(get_app_task)]


def get_app_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the plugin.

    Processes the task data to extract information for display in the index view.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing task information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data.get("meta", {})
    return {
        "hostname": meta.get("target", ""),
        "created_by": task.get("created_by"),
        "last_updated_by": task.get("last_updated_by"),
    }


async def get_app_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts: ExecutorHosts,
) -> dict[str, Any]:
    """Assemble the context for the plugin index view.

    Retrieves services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param inventory_api: The Inventory API client for fetching service data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with app-specific information.
    :type context: DefaultContext
    :param executor_hosts: The executor hosts for the tasks.
    :type executor_hosts: ExecutorHosts
    :return: An updated context dictionary containing app-related data.
    :rtype: dict[str, Any]
    """
    # TODO: Replace TaskOwner.ANY with your TaskOwner enum value once added
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_app_task_info,
        executor_hosts,
        context,
        TaskOwner.ANY,
        alert_on_fail_default=False,
    )
