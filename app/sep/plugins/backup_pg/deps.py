"""Define dependencies for the Backups plugin."""

import logging
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form, Request
from fastapi.encoders import jsonable_encoder

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
from app.sep.plugins.backup.models import (
#    BackupConfig,
#    BackupConfigAll,
#    BackupConfigServer,
#    BackupCreate,
    BackupType,
#    UploadProvider,
)
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)


def get_backups_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Backups plugin.

    Processes the task data to extract hostname and tables information.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing hostname and tables information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    backup_server = task_config["SERVER_LIST"][0]

    return {
        "hostname": meta["target"],
        "host": backup_server.get("HOST"),
        "port": backup_server.get("PORT") or 3306,
        "upload": ", ".join(backup_server.get("UPLOAD")),
        "backup_type": BackupType(backup_server.get("BACKUP_TYPE")).name,
    }


async def get_backups_index_context(
    request: Request,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
) -> dict[str, Any]:
    """Assemble the context for the Backups plugin index view.

    Retrieves PostgreSQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param request: The HTTP request object.
    :type request: Request
    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Backups-specific information.
    :type context: DefaultContext
    :return: An updated context dictionary containing Backups-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        request,
        inventory_api,
        tasks_api,
        get_backups_task_info,
        context,
        TaskOwner.BACKUP_PG,
        alert_on_fail_default=True,
    )
