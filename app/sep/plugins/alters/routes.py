"""Define routes for the alters plugin."""

import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.inventory.models import ServiceTypeEnum
from app.sep.config import sep_settings
from app.sep.deps import DefaultContext, InventoryAPI, IsAuthenticated, TaskAPI
from app.sep.plugins.alters.deps import AltersGeneratedTask, AltersTask
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alters_index(
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> HTMLResponse:
    """Homepage of alters plugin."""
    mysql_services = await inventory_api.get(
        "/services/", params={"service_type": ServiceTypeEnum.MYSQL}
    )
    for service in mysql_services:
        service["schemas"] = await inventory_api.get(
            f"/services/{service['id']}/schemas/",
        )
    tasks = []
    for task in await tasks_api.get("/", params={"owner": "alters"}):
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
        history = await tasks_api.get(f"/{task['name']}/history/")
        for hist in history:
            match TaskHistoryStatusEnum(hist["status"]):
                case TaskHistoryStatusEnum.SUCCESS | TaskHistoryStatusEnum.FAILED:
                    history_tasks.append(hist)
                case TaskHistoryStatusEnum.PENDING:
                    scheduled_tasks.append(hist)
                case TaskHistoryStatusEnum.RUNNING:
                    running_tasks.append(hist)
    executor_hosts = await tasks_api.get("/hosts/")
    context.update(
        {
            "executor_hosts": list(executor_hosts.values()),
            "mysql_services": mysql_services,
            "tasks": tasks,
            "pending_tasks": scheduled_tasks,
            "running_tasks": running_tasks,
            "history_tasks": history_tasks,
        },
    )
    logger.info("CONTEXT: %s", context)
    return templates.TemplateResponse(
        request=request,
        name="alters/index.html",
        context=context,
    )


@router.post("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alters_create(
    task: AltersGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create an alter task."""
    logger.debug("Create alters task: %s", task)
    # TODO: validate response  # noqa: TD002, TD003
    await task_api.post(
        "/generate/",
        json=task.model_dump(),
    )  # TODO: Proper error for unique constraint  # noqa: TD002, TD003
    return RedirectResponse(
        "/alters",
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alters_detail(
    task: AltersTask,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve alters task."""
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
    context["history"] = await tasks_api.get(f"/{task['name']}/history/")
    context["stats"] = await tasks_api.get(f"/stats/{task['name']}")
    return templates.TemplateResponse(
        request=request,
        name="alters/details.html",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated],
    response_class=RedirectResponse,
)
async def alters_execute(
    task: AltersTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Execute alters task."""
    await tasks_api.post(
        f"/execute/{task['name']}"
    )  # TODO: send meta form fields  # noqa: TD002, TD003
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated],
    response_class=RedirectResponse,
)
async def alters_delete(
    task: AltersTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete alters task."""
    await tasks_api.delete(f"/{task['name']}")
    return RedirectResponse("/alters", status_code=status.HTTP_303_SEE_OTHER)
