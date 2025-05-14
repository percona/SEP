from typing import Any

import yaml
from fastapi import Request

from app.sep.deps import DefaultContext, get_tasks_context, InventoryAPI, TaskAPI
from app.tasks.models import TaskOwner


def get_restores_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Restores plugin.

    Processes the task data to extract hostname and tables information.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing hostname and tables information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    restore_server = task_config["SERVER_LIST"][0]

    return {
        "hostname": meta["target"],
        "host": restore_server.get("HOST"),
        "port": restore_server.get("PORT") or 3306,
        "upload": ", ".join(restore_server.get("UPLOAD")),
        # "restore_type": RestoreType(restore_server.get("RESTORE_TYPE")).name,
    }


async def get_restores_index_context(
    request: Request,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
) -> dict[str, Any]:
    """Assemble the context for the Restores plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param request: The HTTP request object.
    :type request: Request
    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Restores-specific information.
    :type context: DefaultContext
    :return: An updated context dictionary containing Restores-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        request,
        inventory_api,
        tasks_api,
        get_restores_task_info,
        context,
        TaskOwner.RESTORES,
    )
