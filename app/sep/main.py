# Copyright (C) 2025 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define SEP routes."""

import logging.config
from traceback import format_exception
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError
from jwt import InvalidTokenError
from pydantic import ValidationError
from starlette.staticfiles import StaticFiles

from app.core.auth.exceptions import BaseAuthProviderException
from app.core.auth.utils import get_user_model
from app.core.config import create_app, default_lifespan, settings
from app.core.security import crypto_timestamp_serializer
from app.core.utils import import_var, run_pydantic_type_validator
from app.core.utils.fields import URIPath
from app.sep.config import CsrfSettings, sep_settings
from app.sep.deps import (
    AccessTokenCookie,
    get_base_url,
    get_current_user,
    get_default_context,
    get_tasks_index_context,
    IsAuthenticated,
    IsCsrfValidated,
    IsNotAuthenticated,
)
from app.sep.exceptions import LoginRedirectException
from app.sep.middleware import CSRFMiddleware, messages
from app.sep.utils.react_assets import get_react_assets

logger = logging.getLogger(__name__)


lifespan = default_lifespan if __name__ == "__main__" else None
sep_app = create_app(
    lifespan=lifespan,
    allowed_hosts=sep_settings.ALLOWED_HOSTS,
    security_headers=sep_settings.SECURITY_HEADERS,
)
sep_app.add_middleware(CSRFMiddleware)
sep_app.add_middleware(messages.MessagesMiddleware)
sep_app.mount("/static", StaticFiles(directory=sep_settings.STATIC_DIR), name="static")


@CsrfProtect.load_config
def get_csrf_config() -> CsrfSettings:
    """Load and return the CSRF configuration settings.

    :return: An instance of `CsrfSettings` containing CSRF protection configuration.
    :rtype: CsrfSettings
    """
    return CsrfSettings()


imported_plugins = set()
for plugin in sep_settings.PLUGINS:
    router = import_var(plugin.router_path)
    sep_app.include_router(router, prefix=plugin.uri_path)
    imported_plugins.add(plugin.module_name.split(".")[-1])

if {
    "alters",
    "archives",
    "tasks",
    "backup",
    "backup_mongo",
    "checksums",
} & imported_plugins:
    from app.sep.routes.periodic_tasks import router as periodic_tasks_router
    from app.sep.routes.stop_task import router as stop_task_router
    from app.sep.routes.stream_logs import router as stream_logs_router

    sep_app.include_router(stream_logs_router, prefix="/stream-logs")
    sep_app.include_router(periodic_tasks_router, prefix="/periodic")
    sep_app.include_router(stop_task_router, prefix="/stop-task")

User = get_user_model()
templates = sep_settings.TEMPLATES


@sep_app.exception_handler(status.HTTP_500_INTERNAL_SERVER_ERROR)
async def internal_error_handler(
    request: Request,
    exc: BaseException,
) -> HTMLResponse:
    """Load custom error page."""
    base_url = get_base_url(request)
    logger.exception("Unhandled exception:", exc_info=exc)
    user = await get_current_user(request)
    messages.error(
        request,
        "Internal Server Error. Please contact the administrators for help.",
        sticky=True,
    )
    return templates.TemplateResponse(
        request=request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        name="error.html",
        context={
            "exception": "".join(format_exception(exc, limit=-1, chain=False)),
            **get_default_context(request, user, base_url),
        },
    )


@sep_app.exception_handler(status.HTTP_404_NOT_FOUND)
async def custom_404_handler(
    request: Request,
    exc: BaseException,
) -> Response:
    """Load custom 404 page."""
    base_url = get_base_url(request)
    try:
        user = await get_current_user(request)
    except LoginRedirectException as redirect_exc:
        return RedirectResponse(
            redirect_exc.location,
            status_code=redirect_exc.status_code,
        )
    return templates.TemplateResponse(
        request=request,
        status_code=status.HTTP_404_NOT_FOUND,
        name="404.html",
        context={"exception": exc, **get_default_context(request, user, base_url)},
    )


@sep_app.exception_handler(CsrfProtectError)
async def csrf_protect_exception_handler(_: Request, exc: CsrfProtectError) -> None:
    """Handle exceptions raised by CSRF protection."""
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@sep_app.exception_handler(BaseAuthProviderException)
async def auth_provider_exception_handler(
    request: Request, exc: BaseAuthProviderException
) -> RedirectResponse:
    """Handle exceptions raised by auth providers."""
    logger.exception("Error connecting to auth provider:", exc_info=exc)
    messages.error(request, exc.detail, sticky=True)
    next_path = request.query_params.get("next", request.url.path)
    redirect_location = request.url_for("login").path
    if next_path and next_path != redirect_location:
        redirect_location += f"?next={next_path}"
    response = RedirectResponse(
        redirect_location, status_code=status.HTTP_303_SEE_OTHER
    )
    response.delete_cookie(sep_settings.SESSION.COOKIE_NAME)
    return response


@sep_app.exception_handler(HTTPException)
async def default_exception_handler(
    request: Request, exc: HTTPException
) -> RedirectResponse:
    """Define default exception handler."""
    error_detail = exc.detail
    messages.error(request, error_detail)
    return RedirectResponse(
        request.headers.get("referer", "/"), status_code=status.HTTP_303_SEE_OTHER
    )


@sep_app.get("/login", dependencies=[IsNotAuthenticated])
async def login_form(
    request: Request, next_path: Annotated[str, Query(alias="next")] = "/"
) -> HTMLResponse:
    """Display login form."""
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "csrf_token": request.state.csrf_token,
            "messages": messages.get_messages(request),
            "next_path": next_path,
        },
    )


@sep_app.post("/login", dependencies=[IsNotAuthenticated, IsCsrfValidated])
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    next_path: Annotated[str, Query(alias="next")] = "/",
) -> RedirectResponse:
    """Authenticate user from their username and password."""
    # TODO(yan): Prevent malicious account lockout
    # SEP-277
    oauth_token = await User.get_oauth_token(
        username=form_data.username, password=form_data.password
    )
    if not settings.ALLOW_CONCURRENT_SESSIONS:
        await User.invalidate_tokens_for_user(
            form_data.username, exclude_tokens=[oauth_token.access_token]
        )
    try:
        next_path = run_pydantic_type_validator(URIPath, next_path)
    except ValidationError:
        next_path = "/"
    response = RedirectResponse(next_path, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        **sep_settings.SESSION.model_dump(by_alias=True),
        value=crypto_timestamp_serializer.dumps(oauth_token.access_token),
        httponly=True,
    )
    return response


@sep_app.post("/logout", dependencies=[IsAuthenticated, IsCsrfValidated])
async def logout(access_token: AccessTokenCookie) -> RedirectResponse:
    """Logout route."""
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(sep_settings.SESSION.COOKIE_NAME)
    try:
        await User.invalidate_oauth_token(access_token)
    except (KeyError, InvalidTokenError, ValidationError):
        logger.debug("Failed to invalidate OAuth token", exc_info=True)
    return response


@sep_app.get("/", response_class=HTMLResponse)
async def read_root(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_tasks_index_context)],
) -> HTMLResponse:
    """Homepage route."""
    return templates.TemplateResponse(
        request=request,
        name="homepage.html",
        context=context,
    )


@sep_app.get("/react", response_class=HTMLResponse)
async def react_app(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    """React application route."""
    base_url = get_base_url(request)
    react_assets = get_react_assets()
    return templates.TemplateResponse(
        request=request,
        name="react_app.html",
        context={
            **get_default_context(request, user, base_url),
            "react_assets": react_assets,
        },
    )


if __name__ == "__main__":
    logging.config.dictConfig(settings.LOGGING_CONFIG)

    import uvicorn

    uvicorn.run(
        sep_app,
        host=sep_settings.UVICORN_HOST,
        port=sep_settings.UVICORN_PORT,
        proxy_headers=sep_settings.PROXY_HEADERS,
        ssl_keyfile=sep_settings.SSL_KEYFILE,
        ssl_certfile=sep_settings.SSL_CERTFILE,
        log_config=settings.LOGGING_CONFIG,
    )
