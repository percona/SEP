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

"""Define routes for the checksums plugin."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import FutureDatetime

from app.core.alerts.config import alert_settings
from app.inventory.models import ServiceTypeEnum
from app.sep.config import sep_settings
from app.sep.connectivity import maybe_check_connectivity
from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
    get_chainable_tasks,
    HasNoConflictedRunningTasks,
    InventoryAPI,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.plugins.checksums.deps import (
    ChecksumsGeneratedTask,
    ChecksumsTask,
    extract_service_info,
    get_checksums_api_task_responses,
    get_checksums_index_context,
    get_checksums_task,
    get_checksums_task_status,
    parse_checksums_task_args,
)
from app.sep.plugins.checksums.models import ChecksumTaskResponse
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def checksums_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_checksums_index_context)],
) -> HTMLResponse:
    """Homepage of checksums plugin."""
    context["csrf_token"] = request.state.csrf_token
    return templates.TemplateResponse(
        request=request,
        name="checksums/index.html.j2",
        context=context,
    )


@router.get(
    "/api/",
    dependencies=[IsAuthenticated],
    response_model=list[ChecksumTaskResponse],
)
async def checksums_api_list(
    tasks_api: TaskAPI,
    service_type: ServiceTypeEnum | None = None,
    status: TaskHistoryStatusEnum | None = None,
) -> list[ChecksumTaskResponse]:
    """List checksum tasks as JSON."""
    return await get_checksums_api_task_responses(
        tasks_api,
        service_type=service_type,
        status=status,
    )


@router.get(
    "/api/{task_name}",
    dependencies=[IsAuthenticated],
    response_model=ChecksumTaskResponse,
)
async def checksums_api_detail(
    task_name: str,
    tasks_api: TaskAPI,
) -> ChecksumTaskResponse:
    """Retrieve a checksum task as JSON."""
    task = await get_checksums_task(task_name, tasks_api)
    task_status = await get_checksums_task_status(task.name, tasks_api)
    return ChecksumTaskResponse(
        **task.model_dump(),
        service_type=ServiceTypeEnum.MYSQL,
        status=task_status,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def checksums_create(
    request: Request,
    task: ChecksumsGeneratedTask,
    task_api: TaskAPI,
    *,
    check_connectivity: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    """Create an checksum task."""
    logger.debug("Create checksums task: %s", task)
    await task_api.post(
        "/",
        json=task.model_dump(),
    )
    await maybe_check_connectivity(
        request,
        task_api,
        task.data.get("meta", {}),
        check_connectivity=check_connectivity,
    )

    task_path = request.url_for("checksums_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def checksums_detail(
    task: ChecksumsTask,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> HTMLResponse:
    """Retrieve checksums task."""
    data = task.data
    meta = data["meta"]
    decoded_entities = task.anonymized_entities
    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": task.created_by,
        "last_updated_by": task.last_updated_by,
        "hostname": meta["target"],
        "cmd": f"{meta['command']} {meta['args']}",
        "meta": meta,
        "entities": {entity.name: entity.value for entity in decoded_entities},
        "delete_url": request.url_for("checksums_delete", task_name=task.name),
        "alert_on_fail": task.alert_on_fail,
        "is_edit_enabled": not task.protected,
    }
    task_data.update(extract_service_info(meta))
    task_data.update(parse_checksums_task_args(meta))

    context["task"] = task_data

    try:
        response = await inventory_api.get(
            "/services/",
            params={"service_type": ServiceTypeEnum.MYSQL, "limit": 0},
        )
        services = response["items"]
    except HTTPException as exc:
        services = []
        logger.warning("Failed to get services: %s", exc)

    context["executor_hosts"] = executor_hosts_ctx.with_host(
        task_data["hostname"]
    ).as_template_list()
    context["services"] = services

    # TODO(yan): Refactor/reuse like with get_tasks_context  # noqa: TD003
    response = await tasks_api.get(f"/{task.name}/history/")
    context["history"] = response["items"]
    response = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["running_tasks"] = response["items"]
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")
    context["alert_on_fail_default"] = task_data["alert_on_fail"]
    context["alert_on_fail_available"] = bool(alert_settings.PROVIDERS)
    context["chainable_tasks"] = await get_chainable_tasks(
        tasks_api, task.owner, meta["target"], task.name
    )
    return templates.TemplateResponse(
        request=request,
        name="checksums/details.html.j2",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated, HasNoConflictedRunningTasks],
    response_class=RedirectResponse,
)
async def checksums_execute(
    task: ChecksumsTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
    chain_task_names: Annotated[list[str] | None, Form()] = None,
    chain_on_failure: Annotated[bool | None, Form()] = None,
) -> RedirectResponse:
    """Execute checksums task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={
            "eta": eta,
            "chain_task_names": chain_task_names,
            "chain_on_failure": chain_on_failure,
        },
    )
    return RedirectResponse("/checksums", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/update",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def checksums_update(
    request: Request,
    task_name: str,
    updated_task: ChecksumsGeneratedTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Update checksums task."""
    logger.debug("Updating checksums task: %s", updated_task)
    await tasks_api.put(
        f"/{task_name}",
        json=updated_task.model_dump(),
    )

    return RedirectResponse(
        request.url_for("checksums_detail", task_name=updated_task.name),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def checksums_delete(
    task: ChecksumsTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete checksums task."""
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/checksums", status_code=status.HTTP_303_SEE_OTHER)
