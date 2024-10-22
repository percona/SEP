"""Define routes for the archivers plugin."""

import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.sep.config import sep_settings
from app.sep.deps import DefaultContext, InventoryAPI, IsAuthenticated, TaskAPI
from app.sep.plugins.archives.deps import ArchivesGeneratedTask, ArchivesTask
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def archives_index(
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
    inventory_api: InventoryAPI,
) -> HTMLResponse:
    """Homepage of archives plugin."""
    all_hosts = await inventory_api.get("/")
    tasks = []
    for task in await tasks_api.get("/", params={"owner": "archiver"}):
        data = task["data"]
        taskinfo = {
            "hostname": data["Constraints"][0]["RTarget"],
            "name": task["name"],
            "id": task["id"],
        }
        tasks.append(taskinfo)
    mysql_hosts = []
    for host in all_hosts:
        for service in host["services"]:
            if service["type"] == "mysql":
                host["schemas"] = await inventory_api.get(f"/services/{service['id']}/schemas/")
                mysql_hosts.append(host)
                break
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
            "mysql_hosts": mysql_hosts,
            "tasks": tasks,
            "pending_tasks": scheduled_tasks,
            "running_tasks": running_tasks,
            "history_tasks": history_tasks,
        },
    )
    return templates.TemplateResponse(
        request=request,
        name="archiver/index.html",
        context=context,
    )


@router.post("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def archives_create(
    task: ArchivesGeneratedTask,
    task_api: TaskAPI,
) -> RedirectResponse:
    """Create new archives task."""
    logger.debug("Create archives task: %s", task)
    # TODO: validate response  # noqa: TD002, TD003
    await task_api.post(
        "/generate/",
        json=task.model_dump(),
    )  # TODO: Proper error for unique constraint  # noqa: TD002, TD003
    return RedirectResponse(
        "/archives",
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class  # noqa: TD002, TD003


@router.get("/{task_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def archives_detail(
    task: ArchivesTask,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve archives task."""
    data = task["data"]
    task_config = data["TaskGroups"][0]["Tasks"][0]["Config"]
    meta = data["TaskGroups"][0]["Tasks"][0]["Meta"]
    task_data = {
        "name": task["name"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
        "hostname": data["Constraints"][0]["RTarget"],
        "cmd": f"{task_config['command']} {' '.join(task_config['args'])}",
        "meta": meta,
    }
    context["task"] = task_data
    context["history"] = await tasks_api.get(f"/history/{task['name']}")
    context["stats"] = await tasks_api.get(f"/stats/{task['name']}")
    return templates.TemplateResponse(
        request=request,
        name="archiver/details.html",
        context=context,
    )


@router.post(
    "/{task_name}",
    dependencies=[IsAuthenticated],
    response_class=RedirectResponse,
)
async def archives_execute(
    task: ArchivesTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Execute archives task."""
    await tasks_api.post(
        f"/execute/{task['name']}"
    )  # TODO: send meta form fields  # noqa: TD002, TD003
    return RedirectResponse("/archives", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{task_name}/delete",
    dependencies=[IsAuthenticated],
    response_class=RedirectResponse,
)
async def archives_delete(
    task: ArchivesTask,
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Delete archives task."""
    await tasks_api.delete(f"/{task['name']}")
    return RedirectResponse("/archives", status_code=status.HTTP_303_SEE_OTHER)
