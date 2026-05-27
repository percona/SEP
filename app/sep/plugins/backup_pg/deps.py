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

import asyncio
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form
from fastapi.encoders import jsonable_encoder

from app.core.models import PaginatedResponse
from app.inventory.constants import DEFAULT_POSTGRESQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
    get_check_connectivity_flag,
)
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
from app.sep.plugins.backup_pg.models import (
    BackupConfig,
    BackupConfigAll,
    BackupConfigServer,
    BackupCreate,
    BackupTaskDetailResponse,
    BackupTaskResponse,
    BackupTaskWrite,
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


async def build_backup_task_payload(
    form: BackupCreate,
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the backup task payload from a parsed form.

    :param form: The form data for the Backups creation.
    :type form: BackupCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    :return: A fully constructed ``TaskWrite`` object containing all the necessary
        configuration to create the Backup task.
    :rtype: TaskWrite
    """
    service = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        form.service_id,
        type=ServiceTypeEnum.POSTGRESQL,
    )

    all_config = form.model_dump(
        exclude={
            "task_name",
            "hostname",
            "service_id",
            "backup_type",
        },
        by_alias=True,
    )

    server_config = {
        "alias": service.node.address,
        "backup_type": form.backup_type,
        # for now only localhost allowed for X
        "host": "localhost",  # service.node.address
        "port": service.port,
    }

    backup_config = BackupConfig(
        all_servers=BackupConfigAll.model_validate(all_config),
        server_list=[BackupConfigServer.model_validate(server_config)],
    )

    requirements = "packaging\nPyYAML"
    payload_path = Path(__file__).parent / "payload"

    return TaskWrite(
        name=form.task_name,
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.BACKUP_PG,
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
                CONNECTIVITY_META_PORT_KEY: service.port or DEFAULT_POSTGRESQL_PORT,
                CONNECTIVITY_META_SERVICE_TYPE_KEY: service.type.value,
            },
            "payload": f"file://{payload_path}",
        },
        alert_on_fail=form.alert_on_fail,
    )


async def build_backup_task_payload_from_form(
    form: Annotated[BackupCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build a Backups task payload from an HTML form submission.

    Delegates to :func:`build_backup_task_payload` after FastAPI form parsing.

    :param form: The form data for the Backups creation.
    :type form: BackupCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    :return: A fully constructed ``TaskWrite`` object for the Tasks API.
    :rtype: TaskWrite
    """
    return await build_backup_task_payload(form, inventory_api)


BackupGeneratedTask = Annotated[TaskWrite, Depends(build_backup_task_payload_from_form)]


def backup_create_from_write(body: BackupTaskWrite) -> BackupCreate:
    """Convert a :class:`BackupTaskWrite` body into a :class:`BackupCreate`.

    Always sets ``backup_type`` to :attr:`BackupType.PGBACKREST`; the JSON API
    only schedules pgBackRest tasks today.

    :param body: The JSON request body for backup task creation.
    :type body: BackupTaskWrite
    :return: A :class:`BackupCreate` instance for payload construction.
    :rtype: BackupCreate
    """
    return BackupCreate.model_validate(
        {
            **body.model_dump(mode="json"),
            "backup_type": BackupType.PGBACKREST,
        },
        from_attributes=False,
    )


def extract_latest_task_status(
    histories: Iterable[dict[str, Any]],
) -> TaskHistoryStatusEnum | None:
    """Return the latest known status from a task history payload."""
    for history in histories:
        if (status := history.get("status")) is not None:
            return TaskHistoryStatusEnum(status)
    return None


async def get_backup_pg_task_status(
    task_name: str,
    tasks_api: TaskAPI,
) -> TaskHistoryStatusEnum | None:
    """Fetch the latest execution status for a backup_pg task.

    :param task_name: The name of the task.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to query history.
    :type tasks_api: TaskAPI
    :return: The latest known task status, or ``None`` if no history exists.
    :rtype: TaskHistoryStatusEnum | None
    """
    response = await tasks_api.get(f"/{task_name}/history/")
    return extract_latest_task_status(response["items"])


def _gathered_task_status(
    result: TaskHistoryStatusEnum | BaseException | None,
) -> TaskHistoryStatusEnum | None:
    """Map a ``gather`` result to a status, treating failures as unknown."""
    return None if isinstance(result, BaseException) else result


def build_backup_pg_api_task_response(
    task: Task,
    *,
    status: TaskHistoryStatusEnum | None = None,
) -> BackupTaskResponse:
    """Build a backup_pg task response for the JSON API.

    :param task: The task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :return: A validated backup_pg task API response.
    :rtype: BackupTaskResponse
    """
    data = task.data
    meta = data.get("meta") or {}
    backup_type = ""
    try:
        config = yaml.safe_load(meta.get("config") or "") or {}
        server_list = config.get("SERVER_LIST") or []
        if server_list:
            backup_type = str(server_list[0].get("BACKUP_TYPE", ""))
    except yaml.YAMLError:
        logger.warning("Failed to parse config for backup_pg task %s", task.name)
    return BackupTaskResponse(
        **task.model_dump(),
        hostname=meta.get("target"),
        status=status,
        backup_type=backup_type,
    )


async def get_backup_pg_api_task_responses(
    tasks_api: TaskAPI,
    status: TaskHistoryStatusEnum | None = None,
    offset: int = 0,
    limit: int = 50,
) -> PaginatedResponse[BackupTaskResponse]:
    """Retrieve a page of backup_pg task responses for the JSON API.

    Fetches the full task list (the Tasks API does not yet push status filtering
    down for derived plugins), gathers latest statuses in parallel, and slices
    ``[offset : offset + limit]`` after the optional status filter so the
    response ``total`` reflects the filtered count.

    :param tasks_api: The TaskAPI instance used to query backup tasks.
    :type tasks_api: TaskAPI
    :param status: Optional latest-history status filter.
    :type status: TaskHistoryStatusEnum | None
    :param offset: Zero-based starting offset for the page slice.
    :type offset: int
    :param limit: Maximum items returned for the page.
    :type limit: int
    :return: The paginated backup task responses matching the requested filters.
    :rtype: PaginatedResponse[BackupTaskResponse]
    """
    response = await tasks_api.get(
        "/",
        params={"owner": TaskOwner.BACKUP_PG.value, "limit": 0},
    )
    tasks = [Task.model_validate(item) for item in response["items"]]
    statuses = await asyncio.gather(
        *(get_backup_pg_task_status(task.name, tasks_api) for task in tasks),
        return_exceptions=True,
    )
    normalized = [_gathered_task_status(item) for item in statuses]
    pairs = [
        (task, task_status)
        for task, task_status in zip(tasks, normalized, strict=True)
        if status is None or task_status == status
    ]
    items = [
        build_backup_pg_api_task_response(task, status=task_status)
        for task, task_status in pairs[offset : offset + limit]
    ]
    return PaginatedResponse[BackupTaskResponse](
        items=items,
        total=len(pairs),
        offset=offset,
        limit=limit,
    )


async def build_backup_pg_api_detail_response(
    task: Task,
    tasks_api: TaskAPI,
) -> BackupTaskDetailResponse:
    """Build a backup_pg task detail response for the JSON API.

    :param task: The task to render.
    :type task: Task
    :param tasks_api: The TaskAPI instance used to fetch history.
    :type tasks_api: TaskAPI
    :return: A validated backup_pg task detail API response.
    :rtype: BackupTaskDetailResponse
    """
    status: TaskHistoryStatusEnum | None
    try:
        status = await get_backup_pg_task_status(task.name, tasks_api)
    except Exception:
        logger.exception("Failed to fetch history for backup_pg task %s", task.name)
        status = None
    base = build_backup_pg_api_task_response(task, status=status)
    return BackupTaskDetailResponse(**base.model_dump())


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
    return await get_task_by_name(tasks_api, task_name, TaskOwner.BACKUP_PG)


BackupsTask = Annotated[Task, Depends(get_backups_task)]

BackupsIndexContext = Annotated[dict[str, Any], Depends(get_backups_index_context)]

CheckConnectivityFlag = Annotated[bool, Depends(get_check_connectivity_flag)]


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
        "port": server_config.get("PORT") or 3306,
    }

    for key, value in all_servers_config.items():
        if key.lower() not in result:
            result[key.lower()] = value

    return result
