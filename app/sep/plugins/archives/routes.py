"""Define routes for the archivers plugin."""

import logging
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.sep.config import sep_settings
from app.sep.deps import DefaultContext, IsAuthenticated, TaskAPI
from app.sep.plugins.archives.deps import (
    ArchivesGeneratedTask,
    ArchivesTask,
    get_archives_index_context,
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def archives_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_archives_index_context)],
) -> HTMLResponse:
    """Homepage of archives plugin."""
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
        "/",
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
    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    purge_item = task_config["PURGE_LIST"][0]
    task_data = {
        "name": task["name"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
        "hostname": meta["target"],
        "meta": meta,
        "source_table": f"{purge_item['SOURCE_DB']}.{purge_item['SOURCE_TABLE']}",
        "dest_table": f"{purge_item['SOURCE_DB']}.{purge_item['DEST_TABLE']}",
    }
    context["task"] = task_data
    context["history"] = await tasks_api.get(f"/{task['name']}/history/")
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
