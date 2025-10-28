# Copyright (C) 2025 Percona LLC
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

"""Define routes for the Tasks Plugin."""

import logging
from typing import Annotated
from zoneinfo import available_timezones

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.core.alerts.config import alert_settings
from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    IsAuthenticated,
    IsCsrfValidated,
    TaskAPI,
)
from app.sep.plugins.tasks.deps import TaskDep
from app.sep.plugins.tasks.models import TaskCreateRequest
from app.tasks.models import (
    TaskBackendEnum,
    TaskExecuteRequest,
    TaskHistoryStatusEnum,
    TaskOwner,
)

logger = logging.getLogger(__name__)

router = APIRouter()

templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def tasks_list(
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Homepage of Tasks Plugin."""
    context["tasks"] = await tasks_api.get("/")
    context["running_tasks"] = await tasks_api.get(
        "/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["available_backends"] = TaskBackendEnum
    context["available_owners"] = TaskOwner
    context["alert_on_fail_available"] = bool(alert_settings.PROVIDERS)
    logger.debug("context: %s", context["running_tasks"])
    return templates.TemplateResponse(
        request=request,
        name="tasks/list.html",
        context=context,
    )


@router.get("/ui/history", dependencies=[IsAuthenticated], response_class=JSONResponse)
async def tasks_json(
    tasks_api: TaskAPI,
) -> JSONResponse:
    """Returns task data as JSON."""
    tasks = await tasks_api.get("/")
    running_tasks = await tasks_api.get(
        "/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )

    return JSONResponse(
        content={
            "tasks": tasks,
            "running_tasks": running_tasks,
        }
    )

@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def task_create(
    request: Request,
    create_task_form: Annotated[TaskCreateRequest, Form()],
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Create task."""
    logger.debug("Create task: %s", create_task_form)
    task_data = create_task_form.model_dump(exclude={"payload", "fmt"})
    task_data["data"] = await tasks_api.post(
        "/transform/",
        json=create_task_form.model_dump(include={"payload", "fmt"}),
        params={"backend": create_task_form.backend},
    )

    await tasks_api.post("/", json=task_data)
    task_path = request.url_for("tasks_detail", task_name=create_task_form.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def tasks_detail(
    task: TaskDep,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve task."""
    context["task"] = task
    if not task.is_template:
        context["periodic_tasks"] = await tasks_api.get(f"/{task.name}/periodic/")
        context["history"] = await tasks_api.get(f"/{task.name}/history/")
        context["running_tasks"] = await tasks_api.get(
            f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
        )
    context["available_owners"] = TaskOwner
    context["task_data"] = task.data
    executor_hosts = await tasks_api.get("/hosts/")
    context["executor_hosts"] = list(executor_hosts)
    context["AVAILABLE_TIMEZONES"] = list(available_timezones())
    return templates.TemplateResponse(
        request=request,
        name="tasks/view.html",
        context=context,
    )


@router.post("/{task_name}", dependencies=[IsAuthenticated, IsCsrfValidated])
async def tasks_execute(
    request: Request,
    task: TaskDep,
    tasks_api: TaskAPI,
    execute_data: Annotated[TaskExecuteRequest, Form()],
) -> RedirectResponse:
    """Execute task."""
    await tasks_api.post(f"/execute/{task.name}", json=execute_data.model_dump())
    task_path = request.url_for("tasks_detail", task_name=task.name)
    return RedirectResponse(task_path, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated, IsCsrfValidated],
)
async def tasks_delete(
    task: TaskDep,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete task."""
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/tasks", status_code=status.HTTP_303_SEE_OTHER)
