"""Define routes for the Tasks Plugin."""

import logging
from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.sep.config import sep_settings
from app.sep.deps import DefaultContext, IsAuthenticated, TaskAPI
from app.sep.plugins.tasks.deps import TaskDep
from app.sep.plugins.tasks.models import TaskCreateRequest
from app.tasks.main import AVAILABLE_OWNERS
from app.tasks.models import TaskBackendEnum, TaskExecuteRequest

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
    context["available_backends"] = TaskBackendEnum
    context["available_owners"] = AVAILABLE_OWNERS
    return templates.TemplateResponse(
        request=request,
        name="tasks/list.html",
        context=context,
    )


@router.post("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def task_create(
    create_task_form: Annotated[TaskCreateRequest, Form()],
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Create task."""
    logger.debug("Create task: %s", create_task_form)
    # TODO: name should be unique  # noqa: TD002, TD003
    task_data = create_task_form.model_dump(exclude={"payload", "fmt"})
    task_data["data"] = await tasks_api.post(
        "/transform/",
        json=create_task_form.model_dump(include={"payload", "fmt"}),
        params={"backend": create_task_form.backend},
    )
    logger.debug(task_data)
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
    context["task"] = task
    context["history"] = await tasks_api.get(f"/{task.name}/history/")
    context["available_owners"] = AVAILABLE_OWNERS
    context["task_data"] = task.data
    executor_hosts = await tasks_api.get("/hosts/")
    context["executor_hosts"] = list(executor_hosts.values())
    return templates.TemplateResponse(
        request=request,
        name="tasks/view.html",
        context=context,
    )


@router.post("/{task_name}", dependencies=[IsAuthenticated])
async def tasks_execute(
    task: TaskDep,
    tasks_api: TaskAPI,
    execute_data: Annotated[TaskExecuteRequest, Form()],
) -> RedirectResponse:
    """Execute task."""
    await tasks_api.post(f"/execute/{task.name}", json=execute_data.model_dump())
    return RedirectResponse("/tasks", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{task_name}/delete", dependencies=[IsAuthenticated])
async def tasks_delete(
    task: TaskDep,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete task."""
    await tasks_api.delete(f"/{task.name}")
    return RedirectResponse("/tasks", status_code=status.HTTP_303_SEE_OTHER)
