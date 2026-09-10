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
from typing import Any

import yaml
from fastapi import Depends, Request

from app.core.exceptions import HTTPConflictException
from app.core.requests import as_json_object
from app.inventory.constants import DEFAULT_POSTGRESQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_pg.models import BackupTaskDetailResponse, BackupTaskResponse
from app.sep.apps.framework import build_default_task_response
from app.sep.apps.shared.backups.edit_form import parse_server_list_config
from app.sep.connectivity import CONNECTIVITY_META_PORT_KEY
from app.sep.deps import TaskAPI
from app.tasks.models import Task, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)


async def check_create_has_no_conflicted_running_tasks(
    request: Request,
    tasks_api: TaskAPI,
) -> None:
    """Reject backup_pg JSON create if an in-flight task already exists by name.

    Mirrors :func:`app.sep.deps.check_for_conflicted_running_tasks`, but reads
    the candidate task name from the raw request JSON instead of a path parameter
    so it can run as a create-route guard before the task is posted. Invalid or
    incomplete request bodies are ignored here so the create model remains the
    single source of ``422`` validation errors.

    :param request: The incoming request carrying the JSON create body.
    :param tasks_api: The TaskAPI instance used to query running/pending history.
    :raises HTTPConflictException: When a RUNNING or PENDING task already
        exists for the candidate task name.
    """
    try:
        payload = await request.json()
    except ValueError:
        return

    if not isinstance(payload, dict):
        return
    task_name = payload.get("task_name")
    if not isinstance(task_name, str) or not task_name:
        return

    for history_status in (
        TaskHistoryStatusEnum.RUNNING,
        TaskHistoryStatusEnum.PENDING,
    ):
        response = as_json_object(
            await tasks_api.get(
                f"/{task_name}/history/",
                params={"status": history_status},
            )
        )
        if response["items"]:
            raise HTTPConflictException("Task is already running or pending.")


HasNoConflictedRunningTasksOnCreate = Depends(
    check_create_has_no_conflicted_running_tasks
)


def _parse_first_server_config(task: Task) -> dict[str, Any]:
    """Parse ``meta['config']`` YAML and return the first ``SERVER_LIST`` entry.

    :param task: The task whose ``meta['config']`` YAML should be parsed.
    :type task: Task
    :return: The first server-config dict, or an empty dict on parse failure or
        when ``SERVER_LIST`` is missing/empty.
    :rtype: dict[str, Any]
    """
    meta = (task.data or {}).get("meta") or {}
    try:
        config = yaml.safe_load(meta.get("config") or "") or {}
    except yaml.YAMLError:
        logger.warning("Failed to parse config for backup_pg task %s", task.name)
        return {}
    server_list = config.get("SERVER_LIST") or []
    return server_list[0] if server_list else {}


def build_backup_pg_api_task_response(
    task: Task,
    *,
    status: TaskHistoryStatusEnum | None = None,
    last_executed_at: datetime | None = None,
    server_config: dict[str, Any] | None = None,
) -> BackupTaskResponse:
    """Build a backup_pg task response for the JSON API.

    :param task: The task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :param last_executed_at: The task's most recent finish time (``max``
        ``finished_at``), or ``None`` until it has finished once.
    :param server_config: Pre-parsed first ``SERVER_LIST`` entry. When ``None``
        (the default) the YAML config is parsed here; callers that already
        parsed it can pass it through to avoid a second ``yaml.safe_load``.
    :type server_config: dict[str, Any] | None
    :return: A validated backup_pg task API response.
    :rtype: BackupTaskResponse
    """
    meta = (task.data or {}).get("meta") or {}
    if server_config is None:
        server_config = _parse_first_server_config(task)
    backup_type = str(server_config.get("BACKUP_TYPE", ""))
    return build_default_task_response(
        BackupTaskResponse,
        task,
        status,
        last_executed_at=last_executed_at,
        extras={
            "hostname": meta.get("target"),
            "backup_type": backup_type,
            "service_type": ServiceTypeEnum.POSTGRESQL,
        },
    )


def build_backup_pg_api_detail_response(
    task: Task,
    *,
    status: TaskHistoryStatusEnum | None = None,
    last_executed_at: datetime | None = None,
) -> BackupTaskDetailResponse:
    """Build a backup_pg task detail response for the JSON API.

    The latest status and finish time are supplied by the framework's
    detail/create pipeline rather than fetched here, so this builder stays a
    sync ``(task, *, status, last_executed_at) -> BackupTaskDetailResponse``
    consumed directly by the derived detail, create, and update routes.

    :param task: The task to render.
    :param status: The latest known execution status for the task.
    :param last_executed_at: The task's most recent finish time (``max``
        ``finished_at``), or ``None`` until it has finished once.
    :return: A validated backup_pg task detail API response.
    """
    meta = (task.data or {}).get("meta") or {}
    server_config = _parse_first_server_config(task)
    base = build_backup_pg_api_task_response(
        task,
        status=status,
        last_executed_at=last_executed_at,
        server_config=server_config,
    )
    return BackupTaskDetailResponse(
        **base.model_dump_with_excluded_fields(),
        host=server_config.get("HOST"),
        port=server_config.get("PORT")
        or meta.get(CONNECTIVITY_META_PORT_KEY)
        or DEFAULT_POSTGRESQL_PORT,
    )


def parse_backup_task_data(task: dict[str, Any]) -> dict[str, Any]:
    """Parse backup task data for editing.

    Extracts configuration from an existing backup task to populate the edit form.

    Delegates the shared ``SERVER_LIST`` parsing to
    :func:`~app.sep.apps.shared.backups.edit_form.parse_server_list_config`, layering on the
    postgres-specific ``port`` fallback (YAML port, then the connectivity-meta
    port, then the default).

    :param task: The task data retrieved from the Tasks API.
    :return: A dictionary containing parsed backup configuration.
    """
    meta = task["data"]["meta"]
    task_config = yaml.safe_load(meta["config"])
    server_config = task_config["SERVER_LIST"][0]
    all_servers_config = task_config.get("ALL_SERVERS", {})

    extra_fields = {
        "port": server_config.get("PORT")
        or meta.get(CONNECTIVITY_META_PORT_KEY)
        or DEFAULT_POSTGRESQL_PORT,
    }
    return parse_server_list_config(
        task, server_config, all_servers_config, extra_fields
    )
