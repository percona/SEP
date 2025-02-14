"""Define SEP routes."""

import logging.config
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError
from jwt import InvalidTokenError
from pydantic import ValidationError
from starlette.staticfiles import StaticFiles

from app.core.auth.utils import get_user_model
from app.core.config import create_app, default_lifespan, settings
from app.core.security import crypto_timestamp_serializer
from app.core.utils import import_var
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

if {"alters", "archives", "tasks"} & imported_plugins:
    from app.sep.routes.periodic_tasks import router as periodic_tasks_router
    from app.sep.routes.stream_logs import router as stream_logs_router

    sep_app.include_router(stream_logs_router, prefix="/stream-logs")
    sep_app.include_router(periodic_tasks_router, prefix="/periodic")

User = get_user_model()
templates = sep_settings.TEMPLATES


# TODO: better errors for external services -- pmm, nomad, casdoor  # noqa: TD002, TD003


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
async def login_form(request: Request) -> HTMLResponse:
    """Display login form."""
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "csrf_token": request.state.csrf_token,
            "messages": messages.get_messages(request),
        },
    )


@sep_app.post("/login", dependencies=[IsNotAuthenticated, IsCsrfValidated])
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> RedirectResponse:
    """Authenticate user from their username and password."""
    oauth_token = await User.get_oauth_token(
        username=form_data.username, password=form_data.password
    )
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
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
