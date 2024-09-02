"""Define SEP routes."""

import json
import logging
from importlib import import_module
from typing import Annotated

from fastapi import FastAPI
from fastapi import Form
from fastapi import Request
from fastapi import status
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from app.core.auth.utils import get_user_model
from app.core.fields import URIPath
from app.sep.config import sep_settings
from app.sep.deps import DefaultContext
from app.sep.deps import get_current_user
from app.sep.deps import get_default_context
from app.sep.deps import IsAuthenticatedCookie
from app.sep.deps import TaskAPI
from app.tasks.main import TRANSLATION_MAPPING
from app.tasks.models import TASK_BACKEND_LOOKUP
from app.tasks.nomad.utils import transform_payload

logger = logging.getLogger(__name__)

sep_app = FastAPI()
sep_app.mount("/static", StaticFiles(directory=sep_settings.STATIC_DIR), name="static")

for plugin in sep_settings.PLUGINS:
    module = import_module(plugin.module_name)
    sep_app.include_router(module.router, prefix=plugin.uri_path)

User = get_user_model()
templates = sep_settings.TEMPLATES


# TODO: Improve exception handlers, maybe use it for redirects
@sep_app.exception_handler(500)
async def custom_error_handler(request, exc):
    """Load custom error page."""
    user = await get_current_user(request.cookies.get(sep_settings.OAUTH.COOKIE_NAME))
    return templates.TemplateResponse(
        request=request,
        status_code=exc.status_code,
        name="error.html",
        context={"exception": exc, **get_default_context(user)},
    )


@sep_app.exception_handler(404)
async def custom_404_handler(request, exc):
    """Load custom 404 page."""
    user = await get_current_user(request.cookies.get(sep_settings.OAUTH.COOKIE_NAME))
    return templates.TemplateResponse(
        request=request,
        status_code=404,
        name="404.html",
        context={"exception": exc, **get_default_context(user)},
    )


@sep_app.get("/oauth/callback")
async def callback(code: str) -> RedirectResponse:
    """Callback route for OAuth."""
    # TODO: Treat possible exceptions here
    oauth_token = await User.get_oauth_token(code)
    response = RedirectResponse(url=sep_settings.OAUTH.POST_LOGIN_URI)
    # TODO: Session X Cookie; Cookies attributes (https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html#cookies)
    # TODO: Consider storing refresh token
    response.set_cookie(
        sep_settings.OAUTH.COOKIE_NAME,
        oauth_token.access_token,
        httponly=True,
    )
    return response


@sep_app.post("/logout", dependencies=[IsAuthenticatedCookie])
async def logout() -> RedirectResponse:
    """Logout route."""
    # TODO: CSRF protection
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(sep_settings.OAUTH.COOKIE_NAME)
    return response


@sep_app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, context: DefaultContext) -> HTMLResponse:
    """Homepage route."""
    return templates.TemplateResponse(
        request=request,
        name="homepage.html",
        context=context,
    )


@sep_app.get("/tasks", response_class=HTMLResponse)
async def tasks_list(
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Tasks index route."""
    context["tasks"] = await tasks_api.get("/")
    context["backends"] = TASK_BACKEND_LOOKUP
    return templates.TemplateResponse(
        request=request,
        name="tasks/list.html",
        context=context,
    )


@sep_app.post("/tasks", response_class=HTMLResponse)
async def task_create(
    taskalias: Annotated[str, Form()],
    taskdef: Annotated[str, Form()],
    format: Annotated[str, Form()],
    taskeng: Annotated[int, Form()],
    tasks_api: TaskAPI,
) -> RedirectResponse:
    """Tasks index route."""
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
                backend = TASK_BACKEND_LOOKUP[payload["taskeng"]]
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


@sep_app.get("/tasks/{task_name}", response_class=HTMLResponse)
async def tasks_detail(
    task_name: str,
    request: Request,
    context: DefaultContext,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Tasks detail route."""
    context["task"] = await tasks_api.get(f"/{task_name}")
    context["history"] = await tasks_api.get(f"/history/{task_name}")
    context["TRANSLATION_MAPPING"] = TRANSLATION_MAPPING
    context["task_data"] = json.loads(context["task"]["data"])
    return templates.TemplateResponse(
        request=request,
        name="tasks/view.html",
        context=context,
    )


@sep_app.post("/tasks/{task_name}", response_class=RedirectResponse)
async def tasks_execute(
    task_name: str,
    tasks_api: TaskAPI,
    redirect_to: Annotated[URIPath, Form()] = "/tasks",
) -> RedirectResponse:
    """Tasks execute route."""
    await tasks_api.post(f"/execute/{task_name}")  # TODO: send meta form fields
    return RedirectResponse(redirect_to, status_code=status.HTTP_303_SEE_OTHER)


@sep_app.post("/tasks/{task_name}/delete", response_class=RedirectResponse)
async def tasks_execute(
    task_name: str,
    tasks_api: TaskAPI,
    redirect_to: Annotated[URIPath, Form()] = "/tasks",
) -> RedirectResponse:
    """Tasks delete route."""
    await tasks_api.delete(f"/{task_name}")
    return RedirectResponse(redirect_to, status_code=status.HTTP_303_SEE_OTHER)


# TODO: take all these logics from routes layer
