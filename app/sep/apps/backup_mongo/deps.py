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
import json
import logging
from datetime import datetime
from typing import Annotated, Any

import yaml
from aiohttp import ClientResponseError
from fastapi import Depends, Form

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_mongo.models import (
    BackupCreate,
    BackupDerivedTaskSummary,
    BackupTaskDetailResponse,
    BackupTaskResponse,
    BackupTaskWrite,
    BackupType,
    OWNER,
)
from app.sep.apps.backup_mongo.schema import BACKUP_MONGO_DERIVED
from app.sep.apps.backup_mongo.spec import (
    BackupMongoResolved,
    build_backup_mongo_spec,
)
from app.sep.apps.framework import (
    build_default_task_response,
    extract_latest_task_status,
    get_task_latest_history,
    make_task_dep,
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
from app.tasks.models import (
    Task,
    TaskHistoryLatestStatus,
    TaskHistoryStatusEnum,
    TaskLogType,
    TaskWrite,
)

logger = logging.getLogger(__name__)

PBM_LATEST_STATUS_TAIL_BYTES = 4096
BACKUP_DERIVED_SUFFIXES = tuple(spec.name_suffix for spec in BACKUP_MONGO_DERIVED)


def backup_derived_task_names(parent_name: str) -> list[str]:
    """Return derived task names for a parent backup config task.

    :param parent_name: The name of the parent ``pbm_config`` task.
    :type parent_name: str
    :return: Derived task names in schema declaration order.
    :rtype: list[str]
    """
    return [f"{parent_name}{suffix}" for suffix in BACKUP_DERIVED_SUFFIXES]


def backup_create_from_write(body: BackupTaskWrite) -> BackupCreate:
    """Convert a :class:`BackupTaskWrite` body into a :class:`BackupCreate` model.

    Always sets ``backup_type`` to ``pbm_config``; POST creates the parent
    config task and derived logical, physical, and status siblings.

    :param body: The JSON request body for backup task creation.
    :type body: BackupTaskWrite
    :return: A :class:`BackupCreate` instance for payload construction.
    :rtype: BackupCreate
    """
    return BackupCreate.model_validate(
        {
            **body.model_dump(mode="json"),
            "backup_type": BackupType.PBM_CONFIG,
        },
        from_attributes=False,
    )


async def build_backup_task_payload(
    form: BackupCreate,
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the payload for a Backups task to be executed.

    :param form: The form data for the Backups creation.
    :type form: BackupCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    :return: A fully constructed ``TaskWrite`` object containing all the
        necessary configuration to create the Backup task.
    :rtype: TaskWrite
    """
    try:
        service = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SERVICE,
            form.service_id,
            type=ServiceTypeEnum.MONGODB,
        )
    except HTTPNotFoundException:
        # PBM tasks run off ``form.hostname`` and the generated config; the
        # service is only fetched to populate ``_service_name`` for PMM, so a
        # service deleted between form load and submit degrades to a node-only
        # annotation.
        service = None

    resolved = BackupMongoResolved(
        service_name=service.name if service is not None else None
    )
    return build_backup_mongo_spec(form, resolved)


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


def build_backup_mongo_api_task_response(
    task: Task,
    *,
    status: TaskHistoryStatusEnum | None = None,
    last_executed_at: datetime | None = None,
) -> BackupTaskResponse:
    """Build a backup task response object for the JSON API.

    :param task: The backup task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :param last_executed_at: The task's most recent finish time (``max``
        ``finished_at``), or ``None`` until it has finished once.
    :return: A validated backup task API response object.
    :rtype: BackupTaskResponse
    """
    data = task.data
    meta = data.get("meta") or {}
    return build_default_task_response(
        BackupTaskResponse,
        task,
        status,
        last_executed_at=last_executed_at,
        extras={
            "hostname": meta.get("target"),
            "backup_type": str(data.get("backup_type", "")),
            "service_type": ServiceTypeEnum.MONGODB,
        },
    )


def _gathered_latest_history(
    result: TaskHistoryLatestStatus | BaseException | None,
) -> TaskHistoryLatestStatus | None:
    """Map a ``gather`` result to a latest-history projection, failures -> None."""
    return None if isinstance(result, BaseException) else result


async def _fetch_latest_pbm_status(
    tasks_api: TaskAPI, pbm_status_tasks: list[dict[str, Any]]
) -> str | None:
    """Return the tail of the latest PBM status task's stdout.

    Streams the ``run-script`` logs for the most recent PBM status history
    record through the tasks API and returns at most
    ``PBM_LATEST_STATUS_TAIL_BYTES`` characters of the concatenated stdout
    content. The rolling buffer is truncated to that window on every append
    so long-running PBM status tasks do not materialize their full log in
    memory for this best-effort UI panel.

    :param tasks_api: The TaskAPI instance used to stream task logs.
    :type tasks_api: TaskAPI
    :param pbm_status_tasks: The list of PBM status history records returned by
        the tasks API, or an empty list when no history exists.
    :type pbm_status_tasks: list[dict[str, Any]]
    :return: The tail of the latest PBM status stdout, or ``None`` when no
        history exists or the stream cannot be read.
    :rtype: str | None
    """
    try:
        pbm_status_id = pbm_status_tasks[0]["id"]
    except (IndexError, KeyError, TypeError):
        return None
    tail = ""
    try:
        async for log_entry in tasks_api.stream(
            f"/history/{pbm_status_id}/logs/",
            params={"step": "run-script"},
        ):
            if not log_entry:
                continue
            log_data = json.loads(log_entry)
            if log_data.get("type") == TaskLogType.STDOUT and log_data.get("msg"):
                tail = (tail + log_data["msg"])[-PBM_LATEST_STATUS_TAIL_BYTES:]
    except (ClientResponseError, ValueError, KeyError):
        logger.exception(
            "Failed to fetch latest_status for backup_mongo task %s",
            pbm_status_id,
        )
        return None
    if not tail:
        return None
    return tail


async def _fetch_backup_derived_detail(
    derived_name: str,
    tasks_api: TaskAPI,
) -> tuple[Task, list[dict[str, Any]]] | None:
    """Fetch a derived backup task and its history, or ``None`` when missing."""
    try:
        derived = await get_backups_task(derived_name, tasks_api)
    except HTTPNotFoundException:
        return None
    history_response = await tasks_api.get(f"/{derived.name}/history/")
    return derived, history_response["items"]


async def build_backup_mongo_api_detail_response(
    task: Task,
    tasks_api: TaskAPI,
) -> BackupTaskDetailResponse:
    """Build a backup task detail response for the JSON API.

    Aggregates latest execution status for the parent ``pbm_config`` task and
    each derived logical, physical, and status sibling. When a status sibling
    exists, includes a tail of its latest stdout for the PBM status panel.

    :param task: The parent backup config task.
    :type task: Task
    :param tasks_api: The TaskAPI instance used to query tasks and history.
    :type tasks_api: TaskAPI
    :return: A validated backup task detail API response object.
    :rtype: BackupTaskDetailResponse
    """
    derived_names = backup_derived_task_names(task.name)
    gather_results = await asyncio.gather(
        get_task_latest_history(tasks_api, task.name),
        *(_fetch_backup_derived_detail(name, tasks_api) for name in derived_names),
        return_exceptions=True,
    )
    parent_latest = _gathered_latest_history(gather_results[0])
    derived_results = gather_results[1:]
    derived_tasks = []
    latest_pbm_status = None

    for derived_detail in derived_results:
        if isinstance(derived_detail, BaseException) or derived_detail is None:
            continue
        derived, history_items = derived_detail
        derived_status = extract_latest_task_status(history_items)
        derived_tasks.append(
            BackupDerivedTaskSummary(
                name=derived.name,
                backup_type=str(derived.data.get("backup_type", "")),
                status=derived_status,
            )
        )
        if derived.data.get("backup_type") == BackupType.PBM_STATUS.value:
            latest_pbm_status = await _fetch_latest_pbm_status(tasks_api, history_items)

    base = build_backup_mongo_api_task_response(
        task,
        status=parent_latest.status if parent_latest else None,
        last_executed_at=parent_latest.finished_at if parent_latest else None,
    )
    return BackupTaskDetailResponse(
        **base.model_dump(),
        derived_tasks=derived_tasks,
        latest_pbm_status=latest_pbm_status,
    )


async def resolve_backup_parent_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Resolve a task name to its parent ``pbm_config`` task when linked.

    When ``task_name`` refers to a derived sibling, fetches and returns the
    parent config task. Otherwise returns the task unchanged.

    :param task_name: The name of the task to resolve.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :type tasks_api: TaskAPI
    :return: The parent backup config task.
    :rtype: Task
    """
    task = await get_backups_task(task_name, tasks_api)
    parent = task.data.get("parent")
    if parent:
        return await get_backups_task(str(parent), tasks_api)
    return task


get_backups_task = make_task_dep(OWNER)

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
    return {
        "config": yaml.safe_load(meta["config"]),
        "parent": data.get("parent"),
        "target": meta["target"],
        "created_at": task["created_at"],
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

    Retrieves MongoDB services and associated tasks, organizing them based on their
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
        service_type=ServiceTypeEnum.MONGODB,
        alert_on_fail_default=True,
    )


BackupsIndexContextDep = Annotated[
    dict[str, Any],
    Depends(get_backups_index_context),
]
