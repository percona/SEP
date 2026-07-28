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

"""Define legacy Jinja routes for the backups plugin.

These Jinja2 routes are deprecated. The JSON API equivalents live under
``/api/apps/backup_mongo/`` and the React UI at ``/backups/mongodb/backups``
(``frontend/packages/plugins/backup_mongo``). Every response from this router
carries the RFC 8594 ``Deprecation: true`` header and emits a WARNING on hit;
the routes remain mounted for Wave 1 cutover and will be removed in Wave 3.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import FutureDatetime

from app.core.alerts.config import alert_settings
from app.core.exceptions import HTTPNotFoundException
from app.sep.apps.backup_mongo.deps import (
    _fetch_latest_pbm_status,
    BackupGeneratedTask,
    BackupsIndexContextDep,
    BackupsTask,
    get_backups_task,
)
from app.sep.apps.backup_mongo.schema import BACKUP_MONGO_DERIVED
from app.sep.apps.framework.cascade import cascade_create_tasks
from app.sep.apps.framework.deprecation import DeprecatedJinja2Route
from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    get_chainable_tasks,
    HasNoConflictedRunningTasks,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter(route_class=DeprecatedJinja2Route)
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def pbm_backups_index(
    request: Request,
    context: BackupsIndexContextDep,
) -> HTMLResponse:
    """Homepage of PBM backup mongo plugin."""
    return templates.TemplateResponse(
        request=request,
        name="backup_mongo/backup/index.html.j2",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def pbm_backups_create(
    request: Request,
    task: BackupGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create new backups task."""
    logger.debug("Create backups task: %s", task)

    await cascade_create_tasks(task_api, task.model_dump(), BACKUP_MONGO_DERIVED)

    task_path = request.url_for("pbm_backups_detail", task_name=task.name)
    return RedirectResponse(
        task_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def pbm_backups_detail(
    task: BackupsTask,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve backups task."""
    data = task.data

    # If the task has a parent, redirect to the parent task detail page
    if data.get("parent"):
        task_path = request.url_for("pbm_backups_detail", task_name=data.get("parent"))
        return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)

    meta = data["meta"]
    # Probe for the incremental sibling before linking a Run control. Groups
    # created before this release only gain ``-incremental`` on edit/backfill;
    # linking a missing task would 404 on execute.
    incremental_name = f"{task.name}-incremental"
    try:
        await get_backups_task(incremental_name, tasks_api)
    except HTTPNotFoundException:
        has_incremental = False
    else:
        has_incremental = True

    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "created_by": task.created_by,
        "last_updated_by": task.last_updated_by,
        "hostname": meta["target"],
        "meta": meta,
        "backup_type": data["backup_type"],
        "logical_backup_url": request.url_for(
            "pbm_backups_execute", task_name=task.name + "-logical"
        ),
        "physical_backup_url": request.url_for(
            "pbm_backups_execute", task_name=task.name + "-physical"
        ),
        "alert_on_fail": task.alert_on_fail,
    }
    if has_incremental:
        task_data["incremental_backup_url"] = request.url_for(
            "pbm_backups_execute", task_name=incremental_name
        )

    context["task"] = task_data
    response = await tasks_api.get(f"/{task.name}/history/")
    context["history"] = response["items"]
    response = await tasks_api.get(f"/{task.name}-logical/history/")
    context["history_logical"] = response["items"]
    response = await tasks_api.get(f"/{task.name}-physical/history/")
    context["history_physical"] = response["items"]
    if has_incremental:
        response = await tasks_api.get(f"/{incremental_name}/history/")
        context["history_incremental"] = response["items"]
    else:
        context["history_incremental"] = []
    response = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["running_tasks"] = response["items"]
    response = await tasks_api.get(
        f"/{task.name}-logical/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    context["running_tasks"] += response["items"]
    response = await tasks_api.get(
        f"/{task.name}-physical/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    context["running_tasks"] += response["items"]
    if has_incremental:
        response = await tasks_api.get(
            f"/{incremental_name}/history/",
            params={"status": TaskHistoryStatusEnum.RUNNING},
        )
        context["running_tasks"] += response["items"]
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")

    response = await tasks_api.get(f"/{task.name}-status/history/")
    pbm_status_tasks = response["items"]
    context["latest_status"] = await _fetch_latest_pbm_status(
        tasks_api, pbm_status_tasks
    )

    context["alert_on_fail_default"] = task.alert_on_fail
    context["alert_on_fail_available"] = bool(alert_settings.PROVIDERS)
    context["chainable_tasks"] = await get_chainable_tasks(
        tasks_api, task.owner, meta["target"], task.name
    )

    return templates.TemplateResponse(
        request=request,
        name="backup_mongo/backup/details.html.j2",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated, IsCsrfValidated, HasNoConflictedRunningTasks],
    response_class=RedirectResponse,
)
async def pbm_backups_execute(
    request: Request,
    task: BackupsTask,
    tasks_api: TaskAPI,
    eta: Annotated[FutureDatetime | None, Form()] = None,
    chain_task_names: Annotated[list[str] | None, Form()] = None,
    chain_on_failure: Annotated[bool | None, Form()] = None,
) -> RedirectResponse:
    """Execute backups task."""
    await tasks_api.post(
        f"/execute/{task.name}",
        json={
            "eta": eta,
            "chain_task_names": chain_task_names,
            "chain_on_failure": chain_on_failure,
        },
    )
    task_path = request.url_for("pbm_backups_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=RedirectResponse,
)
async def pbm_backups_delete(
    request: Request,
    task: BackupsTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete backups task."""
    await tasks_api.delete(f"/{task.name}")
    await tasks_api.delete(f"/{task.name}-logical")
    task_path = request.url_for("pbm_backups_index")
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)
