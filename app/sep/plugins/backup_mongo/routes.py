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

"""Define routes for the backups plugin."""

import json
import logging
from typing import Annotated, Any

from aiohttp import ClientResponseError
from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import FutureDatetime

from app.core.alerts.config import alert_settings
from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    get_chainable_tasks,
    HasNoConflictedRunningTasks,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.plugins.backup_mongo.deps import (
    BackupGeneratedTask,
    BackupsIndexContextDep,
    BackupsTask,
)
from app.tasks.models import TaskHistoryStatusEnum, TaskLogType

from .restore.routes import router as restore_router

PBM_LATEST_STATUS_TAIL_BYTES = 4096

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES

router.include_router(restore_router, prefix="/restores", tags=["restores"])


async def _fetch_latest_pbm_status(tasks_api: Any, pbm_status_tasks: Any) -> str | None:
    """Return the tail of the latest PBM status task's stdout.

    Streams the ``run-script`` logs for the most recent PBM status history
    record through the tasks API and returns at most
    ``PBM_LATEST_STATUS_TAIL_BYTES`` of the concatenated stdout content.

    :param tasks_api: The tasks API client instance.
    :type tasks_api: Any
    :param pbm_status_tasks: The list of PBM status history records returned by
        the tasks API, or an empty list when no history exists.
    :type pbm_status_tasks: Any
    :return: The tail of the latest PBM status stdout, or ``None`` when no
        history exists or the stream cannot be read.
    :rtype: str | None
    """
    try:
        pbm_status_id = pbm_status_tasks[0]["id"]
    except (IndexError, KeyError, TypeError):
        return None
    chunks = []
    try:
        async for log_entry in tasks_api.stream(
            f"/history/{pbm_status_id}/logs/",
            params={"step": "run-script"},
        ):
            if not log_entry:
                continue
            log_data = json.loads(log_entry)
            if log_data.get("type") == TaskLogType.STDOUT and log_data.get("msg"):
                chunks.append(log_data["msg"])
    except (ClientResponseError, ValueError, KeyError):
        logger.exception(
            "Failed to fetch latest_status for backup_mongo task %s",
            pbm_status_id,
        )
        return None
    if not chunks:
        return None
    return "".join(chunks)[-PBM_LATEST_STATUS_TAIL_BYTES:]


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

    # Create the config task
    await task_api.post(
        "/",
        json=task.model_dump(),
    )

    # Create a logical backup task
    logical_task = task.model_copy()
    logical_task.data["backup_type"] = "pbm_logical"
    logical_task.name = f"{task.name}-logical"
    logical_task.data["parent"] = task.name
    logical_task.data["payload"] = logical_task.data["payload"].replace(
        "pbm_config", "pbm_logical"
    )

    await task_api.post(
        "/",
        json=logical_task.model_dump(),
    )

    # Create a physical backup task
    physical_task = task.model_copy()
    physical_task.data["backup_type"] = "pbm_physical"
    physical_task.name = f"{task.name}-physical"
    physical_task.data["parent"] = task.name
    physical_task.data["payload"] = logical_task.data["payload"].replace(
        "pbm_logical", "pbm_physical"
    )

    await task_api.post(
        "/",
        json=physical_task.model_dump(),
    )

    # Create a physical backup task
    status_task = task.model_copy()
    status_task.data["backup_type"] = "pbm_status"
    status_task.name = f"{task.name}-status"
    status_task.data["parent"] = task.name
    status_task.data["payload"] = logical_task.data["payload"].replace(
        "pbm_physical", "pbm_status"
    )

    await task_api.post(
        "/",
        json=status_task.model_dump(),
    )

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

    context["task"] = task_data
    context["history"] = await tasks_api.get(f"/{task.name}/history/")
    context["history_logical"] = await tasks_api.get(f"/{task.name}-logical/history/")
    context["history_physical"] = await tasks_api.get(f"/{task.name}-physical/history/")
    context["running_tasks"] = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["running_tasks"] += await tasks_api.get(
        f"/{task.name}-logical/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    context["running_tasks"] += await tasks_api.get(
        f"/{task.name}-physical/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    context["stats"] = await tasks_api.get(f"/stats/{task.name}")

    pbm_status_tasks = await tasks_api.get(f"/{task.name}-status/history/")
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
