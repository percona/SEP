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

from app.core.pagination import PaginatedResponse, Pagination
from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
    get_created_entity,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.framework import (
    build_default_task_response,
    build_task_list_responses,
    make_task_dep,
)
from app.sep.plugins.mysql_backups.models import (
    BackupConfig,
    BackupConfigAll,
    BackupConfigServer,
    BackupCreate,
    BackupResponse,
    BackupType,
)
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)


async def build_backup_task_payload_from_model(
    form: BackupCreate,
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build a ``TaskWrite`` from a validated ``BackupCreate`` instance.

    Shared between the form-bound FastAPI dependency
    :func:`build_backup_task_payload` and direct JSON-path callers.
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

    upload_providers = list(form.upload)

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
                "_service_name": service.name,
                CONNECTIVITY_META_HOST_KEY: service.node.address,
                CONNECTIVITY_META_PORT_KEY: service.port or DEFAULT_MYSQL_PORT,
                CONNECTIVITY_META_SERVICE_TYPE_KEY: service.type.value,
            },
            "payload": f"file://{payload_path}",
        },
        alert_on_fail=form.alert_on_fail,
    )


async def build_backup_task_payload(
    form: Annotated[BackupCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the backup task payload from form.

    :param form: The form data for the Backups creation.
    :type form: BackupCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    :return: A fully constructed ``TaskWrite`` object.
    :rtype: TaskWrite
    """
    return await build_backup_task_payload_from_model(form, inventory_api)


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

    upload_providers = {
        provider.upper()
        for provider in server_config.get("UPLOAD", [])
        if isinstance(provider, str)
    }
    if "S3" in upload_providers:
        result["s3_bucket"] = all_servers_config.get("S3_BUCKET")
        result["s3_storage_class"] = all_servers_config.get("S3_STORAGE_CLASS")
        result["skip_s3_safety_check"] = all_servers_config.get(
            "SKIP_S3_SAFETY_CHECK", False
        )
    if "GSUTIL" in upload_providers:
        result["gs_bucket"] = all_servers_config.get("GS_BUCKET")
    if "RSYNC" in upload_providers:
        result["rsync_path"] = all_servers_config.get("RSYNC_PATH")

    result["binlog_alternative_host"] = all_servers_config.get(
        "BINLOG_ALTERNATIVE_HOST"
    )
    result["mydumper_verbose"] = all_servers_config.get("MYDUMPER_VERBOSE")
    result["xtrabackup_quiet"] = all_servers_config.get("XTRABACKUP_QUIET")
    result["upload_quiet"] = all_servers_config.get("UPLOAD_QUIET")

    for key, value in all_servers_config.items():
        if key.lower() not in result:
            result[key.lower()] = value

    return result


BackupGeneratedTask = Annotated[TaskWrite, Depends(build_backup_task_payload)]


get_backups_task = make_task_dep(TaskOwner.BACKUPS)

BackupsTask = Annotated[Task, Depends(get_backups_task)]


def _extract_backup_type_from_task(task: Task) -> BackupType | None:  # noqa: PLR0911
    """Read ``BACKUP_TYPE`` out of the task's YAML config, if present."""
    meta = task.data.get("meta") if task.data else None
    raw_config = meta.get("config") if meta else None
    if not raw_config:
        return None
    try:
        config = yaml.safe_load(raw_config)
    except yaml.YAMLError:
        return None
    if not isinstance(config, dict):
        return None
    server_list = config.get("SERVER_LIST")
    if not isinstance(server_list, list) or not server_list:
        return None
    first = server_list[0]
    if not isinstance(first, dict):
        return None
    raw_type = first.get("BACKUP_TYPE")
    if raw_type is None:
        return None
    try:
        return BackupType(raw_type)
    except ValueError:
        return None


def build_mysql_backups_api_task_response(
    task: Task,
    status: TaskHistoryStatusEnum | None = None,
) -> BackupResponse:
    """Build a ``BackupResponse`` for the JSON API.

    :param task: The backups task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :return: A validated backup task API response object.
    :rtype: BackupResponse
    """
    hostname = None
    if task.data:
        meta = task.data.get("meta") or {}
        hostname = meta.get("target")
    return build_default_task_response(
        BackupResponse,
        task,
        status,
        extras={
            "backup_type": _extract_backup_type_from_task(task),
            "hostname": hostname,
        },
    )


async def get_mysql_backups_api_task_responses(
    tasks_api: TaskAPI,
    *,
    pagination: Pagination,
    status: TaskHistoryStatusEnum | None = None,
) -> PaginatedResponse[BackupResponse]:
    """Retrieve a paginated page of backup task responses for the JSON API.

    Latest statuses for the page are resolved in a single batched round-trip to
    the Tasks API rather than one history call per task.

    The ``status`` filter is applied client-side after the page is fetched
    (the Tasks API does not yet expose a server-side latest-status filter).
    When a filter is active, ``total`` reflects the count of items on the
    *current page* after filtering — not the global count of matching
    records — so pagination metadata stays consistent with the returned
    ``items``. When no filter is active, ``total`` reflects the unfiltered
    total reported by the Tasks API.

    :param tasks_api: The Tasks API client.
    :type tasks_api: TaskAPI
    :param pagination: Validated offset/limit window for this page.
    :type pagination: Pagination
    :param status: Optional latest-history status filter (client-side).
    :type status: TaskHistoryStatusEnum | None
    :return: Paginated backup task responses matching the filter.
    :rtype: PaginatedResponse[BackupResponse]
    """
    return await build_task_list_responses(
        tasks_api,
        owner=TaskOwner.BACKUPS.value,
        response_builder=build_mysql_backups_api_task_response,
        pagination=pagination,
        status_filter=status,
    )


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
