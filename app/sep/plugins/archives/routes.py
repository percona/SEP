import logging

from fastapi import APIRouter
from fastapi import Request
from fastapi import status
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from app.sep.config import sep_settings
from app.sep.plugins.archives.deps import ArchivesGeneratedTask
from app.sep.deps import DefaultContext
from app.sep.deps import InventoryAPI
from app.sep.deps import TaskAPI
from app.sep.deps import IsAuthenticated
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
    all_hosts = await inventory_api.get("/")
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
            "archives": tasks,
            "scheduled_tasks": scheduled_tasks,
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
    # TODO: validate response
    await task_api.post(
        "/generate",
        json=task.model_dump(),
    )  # TODO: Proper error for unique constraint
    return RedirectResponse(
        "/archives",
        status_code=status.HTTP_303_SEE_OTHER,
    )  # TODO: Custom redirect class
