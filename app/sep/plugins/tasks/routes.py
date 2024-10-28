"""Define routes for the Tasks Plugin."""

import logging
from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.fields import URIPath
from app.sep.config import sep_settings
from app.sep.deps import DefaultContext, IsAuthenticated, TaskAPI
from app.sep.plugins.tasks.models import TaskCreateRequest
from app.tasks.main import AVAILABLE_OWNERS
from app.tasks.models import TaskBackendEnum, TaskExecuteRequest, TriggerRequest

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
    task_name: str,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve task."""
    context["task"] = await tasks_api.get(
        f"/{task_name}",
    )  # TODO: Use Pydantic/SQLModel models  # noqa: TD002, TD003
    context["history"] = await tasks_api.get(f"/{task_name}/history/")
    context["available_owners"] = AVAILABLE_OWNERS
    context["task_data"] = context["task"]["data"]
    executor_hosts = await tasks_api.get("/hosts/")
    context["executor_hosts"] = list(executor_hosts.values())
    return templates.TemplateResponse(
        request=request,
        name="tasks/view.html",
        context=context,
    )


@router.post("/{task_name}", dependencies=[IsAuthenticated])
async def tasks_execute(
    task_name: str,
    tasks_api: TaskAPI,
    execute_data: Annotated[TaskExecuteRequest, Form()],
) -> RedirectResponse:
    """Execute task."""
    await tasks_api.post(f"/execute/{task_name}", json=execute_data.model_dump())
    return RedirectResponse("/tasks", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{task_name}/delete", dependencies=[IsAuthenticated])
async def tasks_delete(
    task_name: str,
    tasks_api: TaskAPI,
    redirect_to: Annotated[URIPath, Form()] = "/tasks",
) -> RedirectResponse:
    """Delete task."""
    await tasks_api.delete(f"/{task_name}")
    return RedirectResponse(redirect_to, status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/trigger",
    dependencies=[IsAuthenticated],
)
async def trigger_task_name(
    task_name: str,
    tasks_api: TaskAPI,
    trigger_data: Annotated[TriggerRequest, Form()],
) -> RedirectResponse:
    """Trigger task."""
    logger.debug("triggering task %s", task_name)
    await tasks_api.post(f"/trigger/{task_name}", json=trigger_data.model_dump())

    return RedirectResponse("/tasks", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/schdule",
    dependencies=[IsAuthenticated],
)
async def schedule_task_name(
    task_name: str,
    tasks_api: TaskAPI,
    period: Annotated[str, Form()],
    execute_data: Annotated[TaskExecuteRequest, Form()] | None = None,
) -> RedirectResponse:
    """Schdule task."""
    logger.debug("scheduling task %s, %s, %s", task_name, period, execute_data)

    payload = {
        "period": period,
        "execute_data": execute_data.model_dump() if execute_data else None,
    }

    await tasks_api.post(f"/schedule/{task_name}", json=payload)
