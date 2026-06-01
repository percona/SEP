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
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form, HTTPException
from fastapi.encoders import jsonable_encoder

from app.core.exceptions import HTTPConflictException
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
from app.sep.plugins.framework import extract_latest_task_status
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


_STATUS_FETCH_CONCURRENCY = 10


def _gathered_task_status(
    result: TaskHistoryStatusEnum | BaseException | None,
) -> TaskHistoryStatusEnum | None:
    """Map a ``gather`` result to a status, treating failures as unknown."""
    return None if isinstance(result, BaseException) else result


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
    """Retrieve a paginated page of backup_pg task responses for the JSON API.

    Concurrency for per-task history fetches is bounded by
    :data:`_STATUS_FETCH_CONCURRENCY` so a large page cannot fan-out into
    an unbounded burst of HTTPS calls to the Tasks API.

    The ``status`` filter is applied client-side after the page is fetched
    (the Tasks API does not yet expose a server-side latest-status filter).
    When a filter is active, ``total`` reflects the count of items on the
    *current page* after filtering — not the global count of matching
    records — so pagination metadata stays consistent with the returned
    ``items``. When no filter is active, ``total`` reflects the unfiltered
    total reported by the Tasks API.

    :param tasks_api: The TaskAPI instance used to query backup tasks.
    :type tasks_api: TaskAPI
    :param status: Optional latest-history status filter (client-side).
    :type status: TaskHistoryStatusEnum | None
    :param offset: Zero-based start offset for the underlying Tasks listing.
    :type offset: int
    :param limit: Maximum rows to fetch from the Tasks API for this page.
    :type limit: int
    :return: Paginated backup task responses matching the filter.
    :rtype: PaginatedResponse[BackupTaskResponse]
    """
    params = {
        "owner": TaskOwner.BACKUP_PG.value,
        "offset": offset,
        "limit": limit,
    }
    response = await tasks_api.get("/", params=params)
    tasks = [Task.model_validate(item) for item in response["items"]]
    sem = asyncio.Semaphore(_STATUS_FETCH_CONCURRENCY)

    async def _bounded_status(task: Task) -> TaskHistoryStatusEnum | None:
        async with sem:
            return await get_backup_pg_task_status(task.name, tasks_api)

    raw_statuses = await asyncio.gather(
        *(_bounded_status(task) for task in tasks),
        return_exceptions=True,
    )
    task_statuses = [_gathered_task_status(item) for item in raw_statuses]
    items = [
        build_backup_pg_api_task_response(task, status=task_status)
        for task, task_status in zip(tasks, task_statuses, strict=True)
        if status is None or task_status == status
    ]
    total = len(items) if status is not None else response.get("total", len(items))
    return PaginatedResponse[BackupTaskResponse](
        items=items,
        total=total,
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
    except HTTPException:
        logger.exception("Failed to fetch history for backup_pg task %s", task.name)
        status = None
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


async def check_create_has_no_conflicted_running_tasks(
    body: BackupTaskWrite, tasks_api: TaskAPI
) -> None:
    """Reject backup_pg JSON create if an in-flight task already exists by name.

    Mirrors :func:`app.sep.deps.check_for_conflicted_running_tasks`, but reads
    the candidate task name from the request body instead of a path parameter
    so it can run before ``cascade_create_tasks``.

    :param body: The validated create request body.
    :type body: BackupTaskWrite
    :param tasks_api: The TaskAPI instance used to query running/pending history.
    :type tasks_api: TaskAPI
    :raises HTTPConflictException: When a RUNNING or PENDING task already
        exists for ``body.task_name``.
    """
    for history_status in (
        TaskHistoryStatusEnum.RUNNING,
        TaskHistoryStatusEnum.PENDING,
    ):
        response = await tasks_api.get(
            f"/{body.task_name}/history/", params={"status": history_status}
        )
        if response["items"]:
            raise HTTPConflictException("Task is already running or pending.")


HasNoConflictedRunningTasksOnCreate = Depends(
    check_create_has_no_conflicted_running_tasks
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
        "port": server_config.get("PORT")
        or meta.get(CONNECTIVITY_META_PORT_KEY)
        or DEFAULT_POSTGRESQL_PORT,
    }

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

    for key, value in all_servers_config.items():
        if key.lower() not in result:
            result[key.lower()] = value

    return result
