"""Define routes for the Tasks Plugin."""

import logging
from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

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
    context["csrf_token"] = request.state.csrf_token
    context["tasks"] = await tasks_api.get("/")
    context["running_tasks"] = await tasks_api.get(
        "/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["available_backends"] = TaskBackendEnum
    context["available_owners"] = TaskOwner
    logger.debug("context: %s", context["running_tasks"])
    return templates.TemplateResponse(
        request=request,
        name="tasks/list.html",
        context=context,
    )


@router.post(
    "/", dependencies=[IsAuthenticated, IsCsrfValidated], response_class=HTMLResponse
)
async def task_create(
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
    return RedirectResponse("/tasks", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def tasks_detail(
    task: TaskDep,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve task."""
    context["csrf_token"] = request.state.csrf_token
    context["tasks"] = await tasks_api.get("/")
    context["task"] = task
    context["schedule"] = await tasks_api.get(f"/{task.name}/periodic/")
    context["history"] = await tasks_api.get(f"/{task.name}/history/")
    context["running_tasks"] = await tasks_api.get(
        f"/{task.name}/history/", params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    context["available_owners"] = TaskOwner
    context["task_data"] = task.data
    executor_hosts = await tasks_api.get("/hosts/")
    context["executor_hosts"] = list(executor_hosts.values())
    return templates.TemplateResponse(
        request=request,
        name="tasks/view.html",
        context=context,
    )


@router.post("/{task_name}", dependencies=[IsAuthenticated, IsCsrfValidated])
async def tasks_execute(
    task: TaskDep,
    tasks_api: TaskAPI,
    execute_data: Annotated[TaskExecuteRequest, Form()],
) -> RedirectResponse:
    """Execute task."""
    await tasks_api.post(f"/execute/{task.name}", json=execute_data.model_dump())
    return RedirectResponse("/tasks", status_code=status.HTTP_303_SEE_OTHER)


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
