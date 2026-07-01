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

"""Define routes for the Tasks App."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.sep.apps.framework.deprecation import DeprecatedJinja2Route
from app.sep.apps.tasks.deps import TaskDep
from app.sep.config import sep_settings
from app.sep.deps import (
    AVAILABLE_TIMEZONES,
    DefaultContext,
    ExecutorHostsCtx,
    IsAuthenticated,
    TaskAPI,
)
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)

router = APIRouter(route_class=DeprecatedJinja2Route)

templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def tasks_list(
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Render the Tasks app homepage with the current and running task lists.

    :param request: The incoming request used to render the template response.
    :param context: The default template context for the page.
    :param tasks_api: Client used to fetch the task and history lists.
    :return: The rendered Tasks list page.
    """
    response = await tasks_api.get("/")
    context["tasks"] = response["items"]
    response = await tasks_api.get(
        "/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["running_tasks"] = response["items"]
    logger.debug("context: %s", context["running_tasks"])
    return templates.TemplateResponse(
        request=request,
        name="tasks/list.html.j2",
        context=context,
    )


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def tasks_detail(
    task: TaskDep,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> HTMLResponse:
    """Retrieve task."""
    context["task"] = task
    context["tasks"] = [task]
    if not task.is_template:
        response = await tasks_api.get(f"/{task.name}/history/")
        context["history"] = response["items"]
        response = await tasks_api.get(
            f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
        )
        context["running_tasks"] = response["items"]
    context["task_data"] = task.data
    context["executor_hosts"] = executor_hosts_ctx.as_template_list()
    context["AVAILABLE_TIMEZONES"] = AVAILABLE_TIMEZONES
    return templates.TemplateResponse(
        request=request,
        name="tasks/view.html.j2",
        context=context,
    )
