"""Define routes for the alters plugin."""

import logging

from fastapi import APIRouter
from fastapi import Request
from fastapi import status
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from app.sep.config import sep_settings
from app.sep.deps import AltersGeneratedTask
from app.sep.deps import DefaultContext
from app.sep.deps import InventoryAPI
from app.sep.deps import TaskAPI
from app.sep.plugins.alters.deps import AltersTask
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", response_class=HTMLResponse)
async def alters_index(
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> HTMLResponse:
    all_hosts = await inventory_api.get("/")
    mysql_hosts = []
    for host in all_hosts:
        for service in host["services"]:
            if service["type"] == "mysql":
                mysql_hosts.append(host)
                break
    tasks = []
    for task in await tasks_api.get("/"):
        if task.get("owner") == "alters":  # TODO: filter on query
            data = task["data"]
            meta = data["TaskGroups"][0]["Tasks"][0]["Meta"]
            taskinfo = {
                "hostname": data["Constraints"][0]["RTarget"],
                "name": task["name"],
                "table": f'{meta["schema_name"]}.{meta["table_name"]}',
                "id": task["id"],
            }
            tasks.append(taskinfo)
    history_tasks = []
    scheduled_tasks = []
    running_tasks = []
    for task in tasks:
        history = await tasks_api.get(f"/history/{task['name']}")
        for hist in history:
            match TaskHistoryStatusEnum(hist["status"]):
                case TaskHistoryStatusEnum.SUCCESS | TaskHistoryStatusEnum.FAILED:
                    history_tasks.append(hist)
                case TaskHistoryStatusEnum.PENDING:
                    scheduled_tasks.append(hist)
                case TaskHistoryStatusEnum.RUNNING:
                    running_tasks.append(hist)
    context.update(
        {
            "hosts": all_hosts,
            "mysql_hosts": mysql_hosts,
            "tasks": tasks,
            "pending_tasks": scheduled_tasks,
            "running_tasks": running_tasks,
            "history_tasks": history_tasks,
        },
    )
    return templates.TemplateResponse(
        request=request,
        name="alters/index.html",
        context=context,
    )


@router.post("/", response_class=HTMLResponse)
async def alters_create(
    task: AltersGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    logger.debug("Create alters task: %s", task)
    # TODO: validate response
    await task_api.post(
        "/generate",
        json=task.model_dump(),
    )  # TODO: Proper error for unique constraint
    return RedirectResponse(
        "/alters",
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class


@router.get("/{task_name}", response_class=HTMLResponse)
async def alters_detail(
    task: AltersTask,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Tasks detail route."""
    data = task["data"]
    task_config = data["TaskGroups"][0]["Tasks"][0]["Config"]
    meta = data["TaskGroups"][0]["Tasks"][0]["Meta"]
    task_data = {
        "name": task["name"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
        "hostname": data["Constraints"][0]["RTarget"],
        "table": f"{meta['schema_name']}.{meta['table_name']}",
        "cmd": f"{task_config['command']} {' '.join(task_config['args'])}",
        "meta": meta,
    }
    context["task"] = task_data
    context["history"] = await tasks_api.get(f"/history/{task['name']}")
    context["stats"] = await tasks_api.get(f"/stats/{task['name']}")
    return templates.TemplateResponse(
        request=request,
        name="alters/details.html",
        context=context,
    )


@router.post("/{task_name}", response_class=RedirectResponse)
async def alters_execute(
    task: AltersTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Alters execute route."""
    await tasks_api.post(f"/execute/{task['name']}")  # TODO: send meta form fields
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{task_name}/delete", response_class=RedirectResponse)
async def alters_delete(
    task: AltersTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Alters delete route."""
    await tasks_api.delete(f"/{task["name"]}")
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)
