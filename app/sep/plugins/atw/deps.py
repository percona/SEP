"""Define dependencies for the Alters plugin."""

import logging
from typing import Any

from fastapi import Request

from app.sep.deps import (
    DefaultContext,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.tasks.models import TaskOwner

logger = logging.getLogger(__name__)


def get_app_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the plugin.

    Processes the task data to extract information.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing information.
    :rtype: dict[str, Any]
    """
    return {}


async def get_app_index_context(
    request: Request,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
) -> dict[str, Any]:
    """Assemble the context for the plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param request: The HTTP request object.
    :type request: Request
    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with app-specific information.
    :type context: DefaultContext
    :return: An updated context dictionary containing app-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        request,
        inventory_api,
        tasks_api,
        get_app_task_info,
        context,
        TaskOwner.ATW,
    )
