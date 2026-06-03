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
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Annotated, Any

import yaml
from aiohttp import ClientResponseError
from fastapi import Depends, Form, HTTPException, status

from app.core.exceptions import HTTPNotFoundException
from app.core.pagination import fetch_all_dict_items, PaginatedResponse, Pagination
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
from app.sep.plugins.backup_mongo.models import (
    BackupConfig,
    BackupConfigBackup,
    BackupConfigPITR,
    BackupConfigStorage,
    BackupCreate,
    BackupDerivedTaskSummary,
    BackupTaskDetailResponse,
    BackupTaskResponse,
    BackupTaskWrite,
    BackupType,
)
from app.sep.plugins.backup_mongo.schema import BACKUP_MONGO_DERIVED
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskLogType,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)

PBM_LATEST_STATUS_TAIL_BYTES = 4096
BACKUP_DERIVED_SUFFIXES = tuple(spec.name_suffix for spec in BACKUP_MONGO_DERIVED)


def _build_pitr_config(form: BackupCreate) -> dict[str, Any]:
    """Build PITR configuration from form data."""
    return {
        "enabled": form.pitr_enabled,
        "oplogSpanMin": form.pitr_oplog_span_min,
        "compression": form.pitr_compression,
    }


def _build_storage_config(form: BackupCreate) -> dict[str, Any]:
    """Build storage configuration from form data."""
    storage_config = {}
    if form.storage_type == "s3":
        storage_config = {
            "region": form.storage_s3_region,
            "bucket": form.storage_s3_bucket,
            "prefix": form.storage_s3_prefix,
            "endpointUrl": form.storage_s3_endpoint_url,
        }
    elif form.storage_type == "filesystem":
        storage_config = {"path": form.storage_filesystem_path}

    return {"type": form.storage_type, form.storage_type: storage_config}


def _parse_backup_priority(priority_str: str) -> dict[str, float] | None:
    """Parse backup priority YAML string and return as dictionary.

    Parses YAML input (dict format) and returns it as a dictionary
    mapping node addresses to priority values for PBM configuration.

    :param priority_str: YAML string containing priority configuration.
    :type priority_str: str
    :return: Parsed priority dictionary mapping node to priority or None if parsing fails.
    :rtype: dict[str, float] | None
    """
    try:
        priority_parsed = yaml.safe_load(priority_str)
    except yaml.YAMLError:
        logger.warning("Failed to parse backup priority YAML: %s", priority_str)
        return None
    else:
        if priority_parsed is None:
            return None
        if isinstance(priority_parsed, dict):
            return {str(k): float(v) for k, v in priority_parsed.items()}
        logger.warning(
            "Priority must be a dictionary/mapping, got: %s", type(priority_parsed)
        )
        return None


def _build_backup_config_dict(form: BackupCreate) -> dict[str, Any]:
    """Build backup configuration dictionary from form data.

    :param form: The form data containing backup configuration fields.
    :type form: BackupCreate
    :return: A dictionary containing backup configuration settings such as priority,
        compression, compression level, timeouts, oplog span, and parallel collections.
        Returns an empty dictionary if no backup configuration fields are provided.
    :rtype: dict[str, Any]
    """
    has_backup_config = any(
        (
            form.backup_priority,
            form.backup_compression,
            form.backup_compression_level is not None,
            form.backup_timeouts_starting_status is not None,
            form.backup_oplog_span_min is not None,
            form.backup_num_parallel_collections is not None,
        )
    )

    if not has_backup_config:
        return {}

    backup_config_dict = {}

    if form.backup_priority:
        priority_parsed = _parse_backup_priority(form.backup_priority)
        if priority_parsed is not None:
            backup_config_dict["priority"] = priority_parsed

    if form.backup_compression:
        backup_config_dict["compression"] = form.backup_compression

    if form.backup_compression_level is not None:
        backup_config_dict["compressionLevel"] = form.backup_compression_level

    if form.backup_timeouts_starting_status is not None:
        backup_config_dict["timeouts"] = {
            "startingStatus": form.backup_timeouts_starting_status
        }

    if form.backup_oplog_span_min is not None:
        backup_config_dict["oplogSpanMin"] = form.backup_oplog_span_min

    if form.backup_num_parallel_collections is not None:
        backup_config_dict["numParallelCollections"] = (
            form.backup_num_parallel_collections
        )

    return backup_config_dict


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
    except HTTPException as exc:
        # ``RemoteAPI.get`` raises a bare ``fastapi.HTTPException`` on 404, not
        # the project's ``HTTPNotFoundException``. PBM tasks run off
        # ``form.hostname`` and the generated config; the service is only
        # fetched to populate ``_service_name`` for PMM. Fall back to a
        # node-only annotation if the service was deleted between form load
        # and form submit, but re-raise any other error.
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise
        service = None

    pitr = _build_pitr_config(form)
    storage = _build_storage_config(form)
    backup_config_dict = _build_backup_config_dict(form)

    backup_config = BackupConfig(
        storage=BackupConfigStorage.model_validate(storage),
        pitr=BackupConfigPITR.model_validate(pitr),
        backup=BackupConfigBackup.model_validate(backup_config_dict)
        if backup_config_dict
        else None,
        credentials_path=form.credentials_path or None,
    )

    requirements = "packaging\nPyYAML"

    payload_path = Path(__file__).parent / f"{form.backup_type}_payload"

    meta = {
        "config": yaml.dump(
            backup_config.model_dump(by_alias=True, exclude_none=True, mode="json"),
            default_flow_style=False,
            allow_unicode=True,
        ),
        "target": form.hostname,
        "requirements": requirements,
    }
    if service is not None:
        meta["_service_name"] = service.name

    return TaskWrite(
        name=form.task_name,
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.BACKUP_MONGO,
        data={
            "task": "run-python",
            "meta": meta,
            "payload": f"file://{payload_path}",
            "backup_type": form.backup_type,
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


def extract_latest_task_status(
    histories: Iterable[dict[str, Any]],
) -> TaskHistoryStatusEnum | None:
    """Return the latest known status from a task history payload."""
    for history in histories:
        if (status := history.get("status")) is not None:
            return TaskHistoryStatusEnum(status)
    return None


async def get_backup_mongo_task_status(
    task_name: str,
    tasks_api: TaskAPI,
) -> TaskHistoryStatusEnum | None:
    """Fetch the latest execution status for a backup task.

    :param task_name: The name of the backup task.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to query task history.
    :type tasks_api: TaskAPI
    :return: The latest known task status, or ``None`` if no history exists.
    :rtype: TaskHistoryStatusEnum | None
    """
    response = await tasks_api.get(f"/{task_name}/history/")
    return extract_latest_task_status(response["items"])


def build_backup_mongo_api_task_response(
    task: Task,
    *,
    status: TaskHistoryStatusEnum | None = None,
) -> BackupTaskResponse:
    """Build a backup task response object for the JSON API.

    :param task: The backup task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :return: A validated backup task API response object.
    :rtype: BackupTaskResponse
    """
    data = task.data
    meta = data.get("meta") or {}
    return BackupTaskResponse(
        **task.model_dump(),
        hostname=meta.get("target"),
        status=status,
        backup_type=str(data.get("backup_type", "")),
    )


def _backup_parent_list_params(pagination: Pagination) -> dict[str, Any]:
    """Build upstream task-list query params for parent ``pbm_config`` rows."""
    return {
        "owner": TaskOwner.BACKUP_MONGO.value,
        "parent_is_null": "true",
        "backup_type": BackupType.PBM_CONFIG.value,
        **pagination.as_params(),
    }


async def _fetch_latest_task_statuses_for_names(
    tasks_api: TaskAPI,
    names: Sequence[str],
) -> dict[str, TaskHistoryStatusEnum | None]:
    """Resolve latest history status for ``names`` via the tasks batch endpoint."""
    if not names:
        return {}
    try:
        response = await tasks_api.post("/history/latest", json={"names": list(names)})
    except Exception:
        logger.exception("Failed to batch-fetch latest history status for backup list")
        return dict.fromkeys(names)
    return {
        name: TaskHistoryStatusEnum(value) if value is not None else None
        for name, value in response.items()
    }


def _gathered_task_status(
    result: TaskHistoryStatusEnum | BaseException | None,
) -> TaskHistoryStatusEnum | None:
    """Map a ``gather`` result to a status, treating failures as unknown."""
    return None if isinstance(result, BaseException) else result


async def get_backup_mongo_api_task_responses(
    tasks_api: TaskAPI,
    *,
    pagination: Pagination,
    status: TaskHistoryStatusEnum | None = None,
) -> PaginatedResponse[BackupTaskResponse]:
    """Retrieve a page of backup task responses for the JSON API.

    Uses one filtered upstream task list plus one batch latest-status lookup per
    page. When ``status`` is set, walks parent-task pages with bounded ``limit``
    and applies latest-status filtering in-memory before slicing.

    :param tasks_api: The TaskAPI instance used to query backup tasks.
    :type tasks_api: TaskAPI
    :param pagination: Validated offset/limit window for this page.
    :type pagination: Pagination
    :param status: Optional latest-history status filter for the list.
    :type status: TaskHistoryStatusEnum | None
    :return: The paginated backup task responses matching the requested filters.
    :rtype: PaginatedResponse[BackupTaskResponse]
    """
    if status is None:
        response = await tasks_api.get(
            "/",
            params=_backup_parent_list_params(pagination),
        )
        parents = [Task.model_validate(item) for item in response["items"]]
        status_map = await _fetch_latest_task_statuses_for_names(
            tasks_api,
            [task.name for task in parents],
        )
        items = [
            build_backup_mongo_api_task_response(
                task,
                status=status_map.get(task.name),
            )
            for task in parents
        ]
        return PaginatedResponse.from_pagination(
            items,
            response["total"],
            pagination,
        )

    parent_items = await fetch_all_dict_items(
        lambda page_pagination: tasks_api.get(
            "/",
            params=_backup_parent_list_params(page_pagination),
        )
    )
    parents = [Task.model_validate(item) for item in parent_items]
    status_map = await _fetch_latest_task_statuses_for_names(
        tasks_api,
        [task.name for task in parents],
    )
    task_status_pairs = [
        (task, task_status)
        for task in parents
        if (task_status := status_map.get(task.name)) == status
    ]
    page_pairs = pagination.slice(task_status_pairs)
    items = [
        build_backup_mongo_api_task_response(task, status=task_status)
        for task, task_status in page_pairs
    ]
    return PaginatedResponse.from_pagination(
        items,
        len(task_status_pairs),
        pagination,
    )


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
        get_backup_mongo_task_status(task.name, tasks_api),
        *(_fetch_backup_derived_detail(name, tasks_api) for name in derived_names),
        return_exceptions=True,
    )
    parent_status = _gathered_task_status(gather_results[0])
    derived_results = gather_results[1:]
    derived_tasks: list[BackupDerivedTaskSummary] = []
    latest_pbm_status: str | None = None

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

    base = build_backup_mongo_api_task_response(task, status=parent_status)
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
    return await get_task_by_name(tasks_api, task_name, TaskOwner.BACKUP_MONGO)


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
        TaskOwner.BACKUP_MONGO,
        alert_on_fail_default=True,
    )


BackupsIndexContextDep = Annotated[
    dict[str, Any],
    Depends(get_backups_index_context),
]
