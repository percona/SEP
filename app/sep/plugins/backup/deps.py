"""Define dependencies for the Backups plugin."""

import logging
from pathlib import Path
from typing import Annotated, Any

import yaml
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
from app.sep.plugins.backup.models import (
    BackupConfig,
    BackupConfigAll,
    BackupConfigServer,
    BackupCreate,
    BackupType,
    UploadProvider,
)
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)


async def build_backup_task_payload(
    form: Annotated[BackupCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the backup task payload from form.

    Build the payload for a Backups task to be executed.

    :param form: The form data for the Backups creation.
    :type form: BackupCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    :return: A fully constructed `TaskWrite` object containing all the necessary
        configuration to create the Backup task.
    :rtype: TaskWrite
    """
    service = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        form.service_id,
        type=ServiceTypeEnum.MYSQL,
    )

    all_config = form.model_dump(
        exclude={
            "task_name",
            "hostname",
            "service_id",
            "backup_type",
            "encryption_recipient",
        },
        by_alias=True,
    )

    upload_providers = []
    if form.s3_bucket:
        upload_providers.append(UploadProvider.S3)
    if form.rsync_path:
        upload_providers.append(UploadProvider.RSYNC)

    server_config = {
        "alias": service.node.address,
        "backup_type": form.backup_type,
        # for now only localhost allowed for X
        "host": (
            "localhost"
            if form.backup_type == "X"
            else form.binlog_alternative_host
            if form.backup_type == "B" and form.binlog_alternative_host
            else service.node.address
        ),
        "port": service.port,
        "upload": upload_providers,
    }

    if form.encryption_recipient:
        server_config["dir_encrypt_config"] = {
            "encryption_recipient": form.encryption_recipient
        }

    backup_config = BackupConfig(
        all_servers=BackupConfigAll.model_validate(all_config),
        server_list=[BackupConfigServer.model_validate(server_config)],
    )
    requirements = "packaging\nPyYAML\nPyMySQL[rsa,ed25519]\nboto3"
    if form.backup_type == BackupType.MYDUMPER:
        payload_name = "mydumper_payload"
    elif form.backup_type == BackupType.XTRABACKUP:
        payload_name = "xtrabackup_payload"
        requirements += "\nfilelock"
    elif form.backup_type == BackupType.BINLOG:
        payload_name = "binlog_payload"
    else:
        raise ValueError(f"Invalid Backup Type {form.backup_type}")
    payload_path = Path(__file__).parent / payload_name

    return TaskWrite(
        name=form.task_name,
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.BACKUPS,
        data={
            "task": "run-python",
            "meta": {
                "config": yaml.dump(
                    backup_config.model_dump(by_alias=True, exclude_none=True)
                ),
                "target": form.hostname,
                "requirements": requirements,
            },
            "payload": f"file://{payload_path}",
        },
    )


BackupGeneratedTask = Annotated[TaskWrite, Depends(build_backup_task_payload)]


async def get_backups_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Fetch and validate a task for the Backups plugin.

    This function retrieves a task by its name from the Tasks API and validates
    that it is owned by the Backups plugin. If the task does not exist or is not
    owned by Backups, it raises a 404 HTTP exception.

    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :type tasks_api: TaskAPI
    :return: The retrieved task.
    :rtype: Task
    :raises HTTPNotFoundException: If the task is not found or is not owned by Backups.
    """
    return await get_task_by_name(tasks_api, task_name, TaskOwner.BACKUPS)


BackupsTask = Annotated[Task, Depends(get_backups_task)]


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

    Retrieves MySQL services and associated tasks, organizing them based on their
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
    backups_context = await get_tasks_context(
        request,
        inventory_api,
        tasks_api,
        get_backups_task_info,
        context,
        TaskOwner.BACKUPS,
    )
    return {**backups_context, "mysql_services": backups_context["services"]}
