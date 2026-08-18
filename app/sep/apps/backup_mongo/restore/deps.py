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

"""Define dependencies for the Restores plugin."""

import asyncio
import logging
from datetime import datetime
from typing import Annotated, Any

import yaml
from fastapi import Depends

from app.core.exceptions import HTTPNotFoundException
from app.core.pagination import fetch_all_dict_items, PaginatedResponse, Pagination
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_mongo.deps import _gathered_latest_history
from app.sep.apps.backup_mongo.models import BackupType
from app.sep.apps.backup_mongo.restore.models import (
    OWNER,
    RestoreCreate,
    RestoreDerivedTaskSummary,
    RestoreTaskDetailResponse,
    RestoreTaskGroupPayloads,
    RestoreTaskResponse,
    RestoreTaskWrite,
)
from app.sep.apps.backup_mongo.restore.spec import build_restore_payloads
from app.sep.apps.framework import (
    batch_get_latest_statuses,
    build_default_task_response,
    extract_latest_task_status,
    get_task_latest_history,
    make_parent_resolver,
    make_task_dep,
)
from app.sep.apps.framework.api import CascadeCreatePlan
from app.sep.apps.framework.cascade import (
    cascade_create_independent_tasks,
    cascade_delete_tasks,
    CascadeFailure,
    CascadeResult,
)
from app.sep.apps.framework.spec import stamp_form_input
from app.sep.deps import (
    check_group_for_conflicted_running_tasks,
    get_created_entity,
    InventoryAPI,
    reject_if_protected,
    TaskAPI,
)
from app.sep.models import SyncInventoryEntityTypeEnum
from app.tasks.models import (
    Task,
    TaskHistoryStatusEnum,
    TaskWrite,
)

logger = logging.getLogger(__name__)


async def _resolve_service_name(
    form: RestoreCreate,
    inventory_api: InventoryAPI,
) -> str | None:
    """Resolve the service name for PMM annotations.

    Return the name of the service identified by ``form.service_id``, or
    ``None`` when the form does not specify a service. ``service_id`` is
    optional on ``RestoreCreate`` (mongo restores can target a hostname
    directly), so callers must tolerate ``None``.

    :param form: The restore form data.
    :type form: RestoreCreate
    :param inventory_api: The Inventory API to look the service up against.
    :type inventory_api: InventoryAPI
    :return: The resolved service name, or ``None`` when no service was
        specified on the form.
    :rtype: str | None
    """
    if not form.service_id:
        return None
    try:
        service = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SERVICE,
            form.service_id,
            type=ServiceTypeEnum.MONGODB,
        )
    except HTTPNotFoundException:
        return None
    return service.name


def restore_create_from_write(body: RestoreTaskWrite) -> RestoreCreate:
    """Convert a :class:`RestoreTaskWrite` JSON body into :class:`RestoreCreate`.

    ``service_id`` int→str coercion is handled by :class:`RestoreCreate`'s
    ``mode="before"`` validator when the dumped JSON body is re-validated.

    :param body: The JSON request body for restore task creation.
    :type body: RestoreTaskWrite
    :return: A :class:`RestoreCreate` instance for payload construction.
    :rtype: RestoreCreate
    """
    return RestoreCreate.model_validate(
        body.model_dump(mode="json"),
        from_attributes=False,
    )


def restore_update_form_from_write(
    body: RestoreTaskWrite,
    parent_task: Task,
) -> RestoreCreate:
    """Convert a restore update JSON body, pinning identity from the parent config.

    The path parent task owns ``task_name`` and ``backup_type``; the request
    body may only update restore parameters.

    :param body: The JSON request body for restore task update.
    :type body: RestoreTaskWrite
    :param parent_task: The parent restore config task from the URL path.
    :type parent_task: Task
    :return: A :class:`RestoreCreate` instance for payload construction.
    :rtype: RestoreCreate
    """
    return RestoreCreate.model_validate(
        {
            **body.model_dump(mode="json"),
            "task_name": parent_task.name,
            "backup_type": _backup_type_from_parent(parent_task),
        },
        from_attributes=False,
    )


async def update_restore_task_group(
    tasks_api: TaskAPI,
    parent_task: Task,
    form: RestoreCreate,
    inventory_api: InventoryAPI,
) -> CascadeResult:
    """PUT the parent config task and each child leg, best-effort.

    PUTs the parent plus the restore, pbm-list, and optional force-resync legs,
    collecting per-leg failures instead of raising so a mid-cascade error does
    not leave the group half-updated with the failure unreported. The caller
    inspects the result and raises on partial failure.

    :param tasks_api: The TaskAPI instance used to update tasks.
    :param parent_task: The parent restore config task.
    :param form: The restore update input with identity pinned to ``parent_task``.
    :param inventory_api: The Inventory API to look up services.
    :return: The per-leg update outcome across the parent and child legs.
    """
    service_name = await _resolve_service_name(form, inventory_api)
    payloads = build_restore_payloads(form, service_name)
    stamp_form_input(payloads.config_task, form)

    legs = [
        (parent_task.name, payloads.config_task),
        (payloads.restore_task.name, payloads.restore_task),
        (payloads.pbm_list_task.name, payloads.pbm_list_task),
    ]
    if payloads.force_resync_task is not None:
        legs.append((payloads.force_resync_task.name, payloads.force_resync_task))

    result = CascadeResult()
    for name, payload in legs:
        try:
            await tasks_api.put(f"/{name}", json=payload.model_dump())
            result.successes.append(name)
        except Exception as exc:  # noqa: BLE001 — surfaced as HTTP 500 by the route
            result.failures.append(CascadeFailure(name, exc))
    return result


async def build_restore_task_group(
    form: RestoreCreate,
    inventory_api: InventoryAPI,
) -> RestoreTaskGroupPayloads:
    """Build restore config, restore, list, and optional force-resync task payloads.

    Force-resync is only included for physical restores. The service name is
    resolved once and reused across the sub-tasks.

    :param form: The restore creation input.
    :type form: RestoreCreate
    :param inventory_api: The Inventory API to look up services.
    :type inventory_api: InventoryAPI
    :return: Named payloads for config, restore, pbm-list, and optional force-resync legs.
    :rtype: RestoreTaskGroupPayloads
    """
    service_name = await _resolve_service_name(form, inventory_api)
    return build_restore_payloads(form, service_name)


async def build_restore_cascade_plan(
    body: RestoreTaskWrite,
    inventory_api: InventoryAPI,
) -> CascadeCreatePlan:
    """Build the cascade create plan for a restore task group, retaining the form.

    Convert the body to a :class:`RestoreCreate` form and keep it so
    :func:`~app.sep.apps.framework.api.derive_cascade_create_route` can stamp it
    onto the parent config task. The cascade closure POSTs the config parent plus
    its independent restore, pbm-list, and optional force-resync children.

    :param body: The JSON request body for restore task creation.
    :param inventory_api: The Inventory API to look up services.
    :return: The plan carrying the config parent write, form, and cascade closure.
    """
    form = restore_create_from_write(body)
    payloads = await build_restore_task_group(form, inventory_api)
    return CascadeCreatePlan(
        parent_write=payloads.config_task,
        form=form,
        cascade=lambda api: create_restore_task_group(
            api,
            payloads.config_task,
            payloads.restore_task,
            payloads.pbm_list_task,
            payloads.force_resync_task,
        ),
    )


RestoreCascadePlan = Annotated[CascadeCreatePlan, Depends(build_restore_cascade_plan)]


def restore_child_task_names(parent_name: str, backup_type: BackupType) -> list[str]:
    """Return child task names for a parent restore config task.

    :param parent_name: The parent config task name.
    :type parent_name: str
    :param backup_type: The restore backup type from the parent config.
    :type backup_type: BackupType
    :return: Child task names in deletion order (restore leg, list, force-resync).
    :rtype: list[str]
    """
    names = [
        f"{parent_name}-{backup_type.value}",
        f"{parent_name}-pbm-list",
    ]
    if backup_type == BackupType.PBM_PHYSICAL:
        names.append(f"{parent_name}-pbm-force-resync")
    return names


async def create_restore_task_group(
    tasks_api: TaskAPI,
    config_task: TaskWrite,
    restore_task: TaskWrite,
    pbm_list_task: TaskWrite,
    force_resync_task: TaskWrite | None,
) -> None:
    """POST the restore task group; roll back on any failure.

    Thin wrapper over :func:`cascade_create_independent_tasks` that
    dumps each :class:`TaskWrite` to a payload dict and orders them
    parent (config) → restore → pbm-list → optional force-resync. The
    helper owns reverse-DELETE rollback and rollback-DELETE warning
    logging.

    :param tasks_api: The TaskAPI instance used to create tasks.
    :type tasks_api: TaskAPI
    :param config_task: The parent restore-config task payload.
    :type config_task: TaskWrite
    :param restore_task: The restore-leg task payload.
    :type restore_task: TaskWrite
    :param pbm_list_task: The pbm-list helper task payload.
    :type pbm_list_task: TaskWrite
    :param force_resync_task: Optional force-resync task for physical restores.
    :type force_resync_task: TaskWrite | None
    :raises Exception: Re-raises the failing POST after rollback DELETEs complete.
    """
    config_payload = config_task.model_dump()
    children = [restore_task.model_dump(), pbm_list_task.model_dump()]
    if force_resync_task is not None:
        children.append(force_resync_task.model_dump())
    await cascade_create_independent_tasks(tasks_api, config_payload, children)


def _parse_restore_task_config(task: Task) -> dict[str, Any]:
    """Return the YAML config dict embedded in a restore task's meta."""
    meta = task.data.get("meta") or {}
    return yaml.safe_load(meta.get("config") or "") or {}


def _backup_type_from_parent(task: Task) -> BackupType:
    """Read ``backupType`` from a parent restore config task."""
    config = _parse_restore_task_config(task)
    backup_type_str = config.get("backupType")
    if backup_type_str is None:
        raise HTTPNotFoundException(
            detail=f"Task {task.name!r} has no backupType in config",
        )
    return BackupType(backup_type_str)


async def _fetch_restore_parent_tasks(tasks_api: TaskAPI) -> list[Task]:
    """Fetch null-parent and legacy self-parent restore rows in two upstream calls.

    The first call fetches modern restore parent rows (``parent`` is null). The
    second call fetches legacy rows with non-null ``parent`` where
    ``parent == name``.
    """
    null_response, self_parent_response = await asyncio.gather(
        fetch_all_dict_items(
            lambda pagination: tasks_api.get(
                "/",
                params={
                    "owner": OWNER,
                    "parent_is_null": "true",
                    **pagination.model_dump(),
                },
            )
        ),
        fetch_all_dict_items(
            lambda pagination: tasks_api.get(
                "/",
                params={
                    "owner": OWNER,
                    "parent_is_null": "false",
                    "self_parent": "true",
                    **pagination.model_dump(),
                },
            )
        ),
    )
    null_parents = [Task.model_validate(item) for item in null_response]
    self_parents = [Task.model_validate(item) for item in self_parent_response]
    return null_parents + self_parents


def build_restore_mongo_api_task_response(
    task: Task,
    *,
    status: TaskHistoryStatusEnum | None = None,
    last_executed_at: datetime | None = None,
) -> RestoreTaskResponse:
    """Build a restore task response object for the JSON API.

    :param task: The restore task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :param last_executed_at: The task's most recent finish time (``max``
        ``finished_at``), or ``None`` until it has finished once.
    :return: A validated restore task API response object.
    :rtype: RestoreTaskResponse
    """
    config = _parse_restore_task_config(task)
    meta = task.data.get("meta") or {}
    backup_type = config.get("backupType")
    return build_default_task_response(
        RestoreTaskResponse,
        task,
        status,
        last_executed_at=last_executed_at,
        extras={
            "hostname": meta.get("target"),
            "backup_type": str(backup_type) if backup_type is not None else "",
            "backup_source": str(config.get("backupSource", "")),
            "service_type": ServiceTypeEnum.MONGODB,
        },
    )


async def get_restore_mongo_api_task_responses(
    tasks_api: TaskAPI,
    *,
    pagination: Pagination,
    status: TaskHistoryStatusEnum | None = None,
) -> PaginatedResponse[RestoreTaskResponse]:
    """Retrieve a page of restore task responses for the JSON API.

    Uses two filtered upstream task lists (null-parent config rows plus legacy
    self-parent rows) and one batch latest-status lookup per page. When
    ``status`` is set, ``total`` reflects the parent count after the status
    filter.

    :param tasks_api: The TaskAPI instance used to query restore tasks.
    :type tasks_api: TaskAPI
    :param pagination: Validated offset/limit window for this page.
    :type pagination: Pagination
    :param status: Optional latest-history status filter for the list.
    :type status: TaskHistoryStatusEnum | None
    :return: The paginated restore task responses matching the requested filters.
    :rtype: PaginatedResponse[RestoreTaskResponse]
    """
    parents = await _fetch_restore_parent_tasks(tasks_api)

    if status is None:
        page_parents = pagination.slice(parents)
        status_map = await batch_get_latest_statuses(
            tasks_api,
            [task.name for task in page_parents],
        )
        items = [
            build_restore_mongo_api_task_response(
                task,
                status=(latest := status_map.get(task.name)) and latest.status,
                last_executed_at=latest.finished_at if latest else None,
            )
            for task in page_parents
        ]
        return PaginatedResponse.from_pagination(items, len(parents), pagination)

    status_map = await batch_get_latest_statuses(
        tasks_api,
        [task.name for task in parents],
    )
    task_latest_pairs = [
        (task, latest)
        for task in parents
        if (latest := status_map.get(task.name)) is not None and latest.status == status
    ]
    page_pairs = pagination.slice(task_latest_pairs)
    items = [
        build_restore_mongo_api_task_response(
            task, status=latest.status, last_executed_at=latest.finished_at
        )
        for task, latest in page_pairs
    ]
    return PaginatedResponse.from_pagination(
        items,
        len(task_latest_pairs),
        pagination,
    )


async def _fetch_restore_child_detail(
    child_name: str,
    tasks_api: TaskAPI,
) -> tuple[Task, list[dict[str, Any]]] | None:
    """Fetch a restore child task and its history, or ``None`` when missing."""
    try:
        child = await get_restores_task(child_name, tasks_api)
    except HTTPNotFoundException:
        return None
    history_response = await tasks_api.get(f"/{child.name}/history/")
    return child, history_response["items"]


async def build_restore_mongo_api_detail_response(
    task: Task,
    tasks_api: TaskAPI,
) -> RestoreTaskDetailResponse:
    """Build a restore task detail response for the JSON API.

    Aggregates latest execution status for the parent config task and each
    restore, pbm-list, and optional force-resync child.

    :param task: The parent restore config task.
    :type task: Task
    :param tasks_api: The TaskAPI instance used to query tasks and history.
    :type tasks_api: TaskAPI
    :return: A validated restore task detail API response object.
    :rtype: RestoreTaskDetailResponse
    """
    backup_type = _backup_type_from_parent(task)
    child_names = restore_child_task_names(task.name, backup_type)
    gather_results = await asyncio.gather(
        get_task_latest_history(tasks_api, task.name),
        *(_fetch_restore_child_detail(name, tasks_api) for name in child_names),
        return_exceptions=True,
    )
    parent_latest = _gathered_latest_history(gather_results[0])
    child_results = gather_results[1:]
    derived_tasks = []

    for child_detail in child_results:
        if isinstance(child_detail, BaseException) or child_detail is None:
            continue
        child, history_items = child_detail
        derived_tasks.append(
            RestoreDerivedTaskSummary(
                name=child.name,
                status=extract_latest_task_status(history_items),
            )
        )

    base = build_restore_mongo_api_task_response(
        task,
        status=parent_latest.status if parent_latest else None,
        last_executed_at=parent_latest.finished_at if parent_latest else None,
    )
    return RestoreTaskDetailResponse(
        **base.model_dump_with_excluded_fields(),
        derived_tasks=derived_tasks,
    )


get_restores_task = make_task_dep(OWNER)

resolve_restore_parent_task = make_parent_resolver(get_restores_task)


async def get_restore_parent_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Resolve the parent restore config task from a path parameter."""
    return await resolve_restore_parent_task(task_name, tasks_api)


RestoreParentTask = Annotated[Task, Depends(get_restore_parent_task)]


async def get_editable_restore_parent_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Resolve the parent restore task or raise when it is not editable.

    Resolves a satellite name to the parent config task, then gates the
    resolved parent: rejects protected tasks and blocks updates while a run of
    the group is in flight. Checking the conflict against the *resolved* parent
    name (not the raw path) closes the gap where a ``PUT`` addressed at an idle
    child leg could mutate a running group.

    :param task_name: The task name from the URL path; may be a child leg.
    :param tasks_api: The TaskAPI instance used to resolve and gate the parent.
    :raises HTTPConflictException: If the parent is protected or any group member
        has a running/pending run.
    :return: The editable parent restore config task.
    """
    parent_task = await get_restore_parent_task(task_name, tasks_api)
    reject_if_protected(parent_task)
    child_names = restore_child_task_names(
        parent_task.name, _backup_type_from_parent(parent_task)
    )
    await check_group_for_conflicted_running_tasks(
        [parent_task.name, *child_names], tasks_api
    )
    return parent_task


EditableRestoreParent = Annotated[
    Task,
    Depends(get_editable_restore_parent_task),
]


def build_restore_update_form_from_body(
    body: RestoreTaskWrite,
    parent_task: EditableRestoreParent,
) -> RestoreCreate:
    """Build a restore update form from a JSON API request body.

    Converts the body to :class:`RestoreCreate` with ``task_name`` and
    ``backup_type`` pinned from the path parent (rename is not supported on
    edit). Does not mutate tasks; callers pass the result to
    :func:`update_restore_task_group`. Depends on the same editable-parent gate
    as the route so FastAPI resolves and gates the parent once per request.

    :param body: The JSON request body for restore task update.
    :param parent_task: The editable parent restore config task from the URL path.
    :return: A :class:`RestoreCreate` instance for payload construction.
    """
    return restore_update_form_from_write(body, parent_task)


async def delete_restore_task_group(
    tasks_api: TaskAPI,
    parent_task: Task,
) -> None:
    """DELETE every restore child task, then the parent config task.

    :param tasks_api: The TaskAPI instance used to delete tasks.
    :type tasks_api: TaskAPI
    :param parent_task: The parent restore config task.
    :type parent_task: Task
    :raises HTTPException: When any child or parent DELETE fails with a non-404.
    """
    backup_type = _backup_type_from_parent(parent_task)
    result = await cascade_delete_tasks(
        tasks_api,
        parent_task.name,
        restore_child_task_names(parent_task.name, backup_type),
    )
    result.raise_if_failed(op="delete")


RestoreUpdateFormFromBody = Annotated[
    RestoreCreate,
    Depends(build_restore_update_form_from_body),
]
