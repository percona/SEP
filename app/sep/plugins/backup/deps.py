# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define dependencies for the Backups plugin."""

import logging
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form
from fastapi.encoders import jsonable_encoder

from app.inventory.models import ServiceTypeEnum
from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
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
            "alias",
        },
        by_alias=True,
    )

    upload_providers = []
    if form.s3_bucket:
        upload_providers.append(UploadProvider.S3)
    if form.gs_bucket:
        upload_providers.append(UploadProvider.GSUTIL)
    if form.rsync_path:
        upload_providers.append(UploadProvider.RSYNC)

    server_config = {
        "alias": form.alias or service.node.address,
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
        requirements += "\nfilelock"
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
                    jsonable_encoder(backup_config, by_alias=True, exclude_none=True)
                ),
                "target": form.hostname,
                "requirements": requirements,
                "_connectivity_host": service.node.address,
                "_connectivity_port": service.port or 3306,
                "_connectivity_service_type": "MYSQL",
            },
            "payload": f"file://{payload_path}",
        },
        alert_on_fail=form.alert_on_fail,
    )


def parse_backup_task_data(task: dict[str, Any]) -> dict[str, Any]:
    """Parse backup task data for editing.

    Extracts configuration from an existing backup task to populate the edit form.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing parsed backup configuration.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    server_config = task_config["SERVER_LIST"][0]
    all_servers_config = task_config.get("ALL_SERVERS", {})

    result = {
        "name": task["name"],
        "hostname": meta["target"],
        "backup_type": server_config["BACKUP_TYPE"],
        "service_id": None,
        "host": server_config["HOST"],
        "port": server_config.get("PORT"),
        "alias": server_config.get("ALIAS"),
    }

    if "dir_encrypt_config" in server_config:
        result["encryption_recipient"] = server_config["dir_encrypt_config"].get(
            "encryption_recipient"
        )

    upload_providers = server_config.get("UPLOAD", [])
    if "S3" in upload_providers:
        result["s3_bucket"] = all_servers_config.get("s3_bucket")
        result["s3_storage_class"] = all_servers_config.get("s3_storage_class")
        result["skip_s3_safety_check"] = all_servers_config.get(
            "skip_s3_safety_check", False
        )
    if "GSUTIL" in upload_providers:
        result["gs_bucket"] = all_servers_config.get("gs_bucket")
    if "RSYNC" in upload_providers:
        result["rsync_path"] = all_servers_config.get("rsync_path")

    for key, value in all_servers_config.items():
        if key.lower() not in result:
            result[key.lower()] = value

    return result


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
        "port": backup_server.get("PORT"),
        "upload": ", ".join(backup_server.get("UPLOAD")),
        "backup_type": BackupType(backup_server.get("BACKUP_TYPE")).name,
        "created_by": task.get("created_by"),
        "last_updated_by": task.get("last_updated_by"),
    }


async def get_backups_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> dict[str, Any]:
    """Assemble the context for the Backups plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Backups-specific information.
    :type context: DefaultContext
    :param executor_hosts_ctx: The executor hosts context for the Backups tasks.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: An updated context dictionary containing Backups-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_backups_task_info,
        executor_hosts_ctx,
        context,
        TaskOwner.BACKUPS,
        alert_on_fail_default=True,
    )
