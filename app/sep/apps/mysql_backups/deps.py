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
from datetime import datetime
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework import build_default_task_response, make_task_dep
from app.sep.apps.framework.spec import (
    assemble_envelope,
    resolve_refs,
)
from app.sep.apps.mysql_backups.models import (
    BackupCreate,
    BackupResponse,
    BackupType,
    OWNER,
)
from app.sep.apps.mysql_backups.spec import build_backup_spec
from app.sep.apps.shared.backups.edit_form import parse_server_list_config
from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.tasks.models import Task, TaskHistoryStatusEnum, TaskWrite

logger = logging.getLogger(__name__)


async def build_backup_task_payload(
    form: Annotated[BackupCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the backup task payload from a form-urlencoded body.

    The legacy Jinja form path's payload dependency. Resolves the form's
    reference fields and feeds the shared pure
    :func:`~app.sep.apps.mysql_backups.spec.build_backup_spec` through the
    framework's ``assemble_envelope``, the same pair the model-first JSON create
    route uses — so a form-created task's Nomad payload stays byte-identical to a
    JSON-created one.

    :param form: The form data for the Backups creation.
    :type form: BackupCreate
    :param inventory_api: The Inventory API to resolve the service reference.
    :type inventory_api: InventoryAPI
    :return: A fully constructed ``TaskWrite`` object.
    :rtype: TaskWrite
    """
    resolved = await resolve_refs(form, inventory_api)
    return assemble_envelope(
        build_backup_spec(form, resolved),
        resolved,
        name=form.task_name,
        owner=OWNER,
        alert_on_fail=form.alert_on_fail,
    )


def parse_backup_task_data(task: dict[str, Any]) -> dict[str, Any]:
    """Parse backup task data for editing.

    Extracts configuration from an existing backup task to populate the edit form.

    Delegates the shared ``SERVER_LIST`` parsing to
    :func:`~app.sep.apps.shared.backups.edit_form.parse_server_list_config`, layering on the
    mysql-specific alias, encryption recipient, and the mydumper / xtrabackup /
    binlog / upload-quiet keys.

    :param task: The task data retrieved from the Tasks API.
    :return: A dictionary containing parsed backup configuration.
    """
    task_config = yaml.safe_load(task["data"]["meta"]["config"])
    server_config = task_config["SERVER_LIST"][0]
    all_servers_config = task_config.get("ALL_SERVERS", {})

    extra_fields = {
        "port": server_config.get("PORT"),
        "alias": server_config.get("ALIAS"),
    }
    if "dir_encrypt_config" in server_config:
        extra_fields["encryption_recipient"] = server_config["dir_encrypt_config"].get(
            "encryption_recipient"
        )
    extra_fields["binlog_alternative_host"] = all_servers_config.get(
        "BINLOG_ALTERNATIVE_HOST"
    )
    extra_fields["mydumper_verbose"] = all_servers_config.get("MYDUMPER_VERBOSE")
    extra_fields["xtrabackup_quiet"] = all_servers_config.get("XTRABACKUP_QUIET")
    extra_fields["upload_quiet"] = all_servers_config.get("UPLOAD_QUIET")

    return parse_server_list_config(
        task, server_config, all_servers_config, extra_fields
    )


BackupGeneratedTask = Annotated[TaskWrite, Depends(build_backup_task_payload)]


get_backups_task = make_task_dep(OWNER)

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
    *,
    last_executed_at: datetime | None = None,
) -> BackupResponse:
    """Build a ``BackupResponse`` for the JSON API.

    :param task: The backups task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :param last_executed_at: The task's most recent finish time (``max``
        ``finished_at``), or ``None`` until it has finished once.
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
        last_executed_at=last_executed_at,
        extras={
            "backup_type": _extract_backup_type_from_task(task),
            "hostname": hostname,
            "service_type": ServiceTypeEnum.MYSQL,
        },
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
        OWNER,
        service_type=ServiceTypeEnum.MYSQL,
        alert_on_fail_default=True,
    )


BackupsIndexContext = Annotated[dict[str, Any], Depends(get_backups_index_context)]
