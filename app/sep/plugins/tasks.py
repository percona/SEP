"""Define routes for the Tasks Plugin."""

import logging
from typing import Annotated

from fastapi import APIRouter
from fastapi import Form
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from app.core.fields import URIPath
from app.sep.config import sep_settings
from app.sep.deps import DefaultContext
from app.sep.deps import IsAuthenticated
from app.sep.deps import TaskAPI
from app.tasks.main import TRANSLATION_MAPPING
from app.tasks.models import TaskBackendEnum
from app.tasks.nomad.utils import transform_payload

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
    return templates.TemplateResponse(
        request=request,
        name="tasks/list.html",
        context=context,
    )


@router.post("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def task_create(  # TODO: Use pydantic model for request data
    taskalias: Annotated[str, Form()],
    taskdef: Annotated[str, Form()],
    format: Annotated[str, Form()],
    taskeng: Annotated[str, Form()],
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Create task."""
    payload = {
        "taskalias": taskalias,
        "taskdef": taskdef,
        "format": format,
        "taskeng": taskeng,
    }
    logger.debug("Create task: %s", payload)
    # TODO: name should be unique
    for mapping in TRANSLATION_MAPPING["create"]:
        if mapping.old not in payload:
            continue
        match mapping.action:
            case "backend":
                try:
                    backend = TaskBackendEnum(payload["taskeng"])
                except ValueError:  # TODO: Use pydantic model for request validation
                    logger.error(
                        "Backend %s is not supported",
                        payload["taskeng"],
                        exc_info=True,
                    )
                    raise HTTPException(status.HTTP_400_BAD_REQUEST) from None
                match backend:
                    case "nomad":
                        payload[mapping.new] = await transform_payload(
                            payload[mapping.old],
                            payload["format"],
                        )
                    case _:
                        raise NotImplementedError("backend is unsupported")
            case "flatten":
                payload[mapping.new] = payload[mapping.old]
            case "update":
                payload.setdefault(mapping.new, {})
                payload[mapping.new].update({mapping.old: payload[mapping.old]})
            case _:
                payload[mapping.new] = payload[mapping.old]
        del payload[mapping.old]
    logger.debug(payload)
    await tasks_api.post("/", json=payload)
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
    )  # TODO: Use Pydantic/SQLModel models
    context["history"] = await tasks_api.get(f"/history/{task_name}")
    context["TRANSLATION_MAPPING"] = TRANSLATION_MAPPING
    context["task_data"] = context["task"]["data"]
    return templates.TemplateResponse(
        request=request,
        name="tasks/view.html",
        context=context,
    )


@router.post("/{task_name}", dependencies=[IsAuthenticated])
async def tasks_execute(
    task_name: str,
    tasks_api: TaskAPI,
    redirect_to: Annotated[URIPath, Form()] = "/tasks",
) -> RedirectResponse:
    """Execute task."""
    await tasks_api.post(f"/execute/{task_name}")  # TODO: send meta form fields
    return RedirectResponse(redirect_to, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{task_name}/delete", dependencies=[IsAuthenticated])
async def tasks_delete(
    task_name: str,
    tasks_api: TaskAPI,
    redirect_to: Annotated[URIPath, Form()] = "/tasks",
) -> RedirectResponse:
    """Delete task."""
    await tasks_api.delete(f"/{task_name}")
    return RedirectResponse(redirect_to, status_code=status.HTTP_303_SEE_OTHER)
