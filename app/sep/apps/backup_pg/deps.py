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
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form, Request

from app.core.exceptions import HTTPConflictException
from app.inventory.constants import DEFAULT_POSTGRESQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_edit_form import parse_server_list_config
from app.sep.apps.backup_pg.models import (
    BackupPgForm,
    BackupTaskDetailResponse,
    BackupTaskResponse,
    BackupType,
)
from app.sep.apps.backup_pg.spec import build_backup_pg_spec
from app.sep.apps.framework import build_default_task_response, make_task_dep
from app.sep.apps.framework.spec import (
    assemble_envelope,
    resolve_refs,
)
from app.sep.connectivity import CONNECTIVITY_META_PORT_KEY
from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
    get_tasks_context,
    InventoryAPI,
    protected_task_guard,
    TaskAPI,
)
from app.tasks.models import Task, TaskHistoryStatusEnum, TaskOwner, TaskWrite

logger = logging.getLogger(__name__)


async def build_backup_task_payload(
    form: Annotated[BackupPgForm, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the backup task payload from a form-urlencoded body.

    The legacy Jinja form path's payload dependency. Resolves the form's
    reference fields and feeds the shared pure
    :func:`~app.sep.apps.backup_pg.spec.build_backup_pg_spec` through the
    framework's ``assemble_envelope`` — the same pair the model-first JSON create
    route uses — so a form-created task's Nomad payload stays byte-identical to a
    JSON-created one.

    :param form: The form data for the Backups creation.
    :param inventory_api: The Inventory API to resolve the service reference.
    :return: A fully constructed ``TaskWrite`` object.
    """
    resolved = await resolve_refs(form, inventory_api)
    return assemble_envelope(
        build_backup_pg_spec(form, resolved),
        resolved,
        name=form.task_name,
        owner=TaskOwner.BACKUP_PG,
        alert_on_fail=form.alert_on_fail,
    )


BackupGeneratedTask = Annotated[TaskWrite, Depends(build_backup_task_payload)]


get_backups_task = make_task_dep(TaskOwner.BACKUP_PG)

BackupsTask = Annotated[Task, Depends(get_backups_task)]


get_unprotected_backups_task = protected_task_guard(get_backups_task)

UnprotectedBackupsTask = Annotated[Task, Depends(get_unprotected_backups_task)]


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
        response = await tasks_api.get(
            f"/{task_name}/history/",
            params={"status": history_status},
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
    server_config: dict[str, Any] | None = None,
) -> BackupTaskResponse:
    """Build a backup_pg task response for the JSON API.

    :param task: The task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
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
) -> BackupTaskDetailResponse:
    """Build a backup_pg task detail response for the JSON API.

    The latest status is supplied by the framework's detail/create pipeline
    rather than fetched here, so this builder stays a sync
    ``(task, *, status) -> BackupTaskDetailResponse`` consumed directly by the
    derived detail, create, and update routes.

    :param task: The task to render.
    :param status: The latest known execution status for the task.
    :return: A validated backup_pg task detail API response.
    """
    meta = (task.data or {}).get("meta") or {}
    server_config = _parse_first_server_config(task)
    base = build_backup_pg_api_task_response(
        task, status=status, server_config=server_config
    )
    return BackupTaskDetailResponse(
        **base.model_dump(),
        host=server_config.get("HOST"),
        port=server_config.get("PORT")
        or meta.get(CONNECTIVITY_META_PORT_KEY)
        or DEFAULT_POSTGRESQL_PORT,
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
        "port": backup_server.get("PORT")
        or meta.get(CONNECTIVITY_META_PORT_KEY)
        or DEFAULT_POSTGRESQL_PORT,
        "backup_type": BackupType(backup_server.get("BACKUP_TYPE")).name,
    }


async def get_backups_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> dict[str, Any]:
    """Assemble the context for the Backups plugin index view.

    Retrieves PostgreSQL services and associated tasks, organizing them based on their
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
        TaskOwner.BACKUP_PG,
        alert_on_fail_default=True,
    )


BackupsIndexContext = Annotated[dict[str, Any], Depends(get_backups_index_context)]


def parse_backup_task_data(task: dict[str, Any]) -> dict[str, Any]:
    """Parse backup task data for editing.

    Extracts configuration from an existing backup task to populate the edit form.

    Delegates the shared ``SERVER_LIST`` parsing to
    :func:`~app.sep.apps.backup_edit_form.parse_server_list_config`, layering on the
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
