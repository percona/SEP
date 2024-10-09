"""Define SEP routes."""

import logging

from fastapi import FastAPI
from fastapi import Request
from fastapi import status
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from jwt import InvalidTokenError
from pydantic import ValidationError
from starlette.staticfiles import StaticFiles

from app.core.auth.exceptions import HTTPTemporaryRedirectException
from app.core.auth.utils import get_user_model
from app.core.config import settings
from app.core.security import crypto_timestamp_serializer
from app.core.utils import import_var
from app.sep.config import sep_settings
from app.sep.deps import AccessTokenCookie
from app.sep.deps import DefaultContext
from app.sep.deps import get_base_url
from app.sep.deps import get_current_user
from app.sep.deps import get_default_context
from app.sep.deps import IsAuthenticated

logger = logging.getLogger(__name__)

sep_app = FastAPI()
sep_app.mount("/static", StaticFiles(directory=sep_settings.STATIC_DIR), name="static")

for plugin in sep_settings.PLUGINS:
    router = import_var(plugin.router_path)
    sep_app.include_router(router, prefix=plugin.uri_path)


User = get_user_model()
templates = sep_settings.TEMPLATES


# TODO: Improve exception handlers, maybe use it for redirects
# TODO: better errors for external services -- pmm, nomad, casdoor
@sep_app.exception_handler(status.HTTP_500_INTERNAL_SERVER_ERROR)
async def custom_error_handler(
    request: Request,
    exc: BaseException,
) -> RedirectResponse | templates.TemplateResponse:
    """Load custom error page."""
    base_url = get_base_url(request)
    try:
        # TODO: Refactor
        user = await get_current_user(request)
    except HTTPTemporaryRedirectException as redirect_exc:
        return RedirectResponse(
            redirect_exc.location,
            status_code=redirect_exc.status_code,
        )
    status_code = getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)
    return templates.TemplateResponse(
        request=request,
        status_code=status_code,
        name="error.html",
        context={"exception": exc, **get_default_context(user, base_url)},
    )


@sep_app.exception_handler(status.HTTP_404_NOT_FOUND)
async def custom_404_handler(
    request: Request,
    exc: BaseException,
) -> RedirectResponse | templates.TemplateResponse:
    """Load custom 404 page."""
    base_url = get_base_url(request)
    try:
        user = await get_current_user(request)
    except HTTPTemporaryRedirectException as redirect_exc:
        return RedirectResponse(
            redirect_exc.location,
            status_code=redirect_exc.status_code,
        )
    return templates.TemplateResponse(
        request=request,
        status_code=status.HTTP_404_NOT_FOUND,
        name="404.html",
        context={"exception": exc, **get_default_context(user, base_url)},
    )


@sep_app.get("/oauth/callback")
async def callback(code: str) -> RedirectResponse:
    """Define callback route for OAuth."""
    # TODO: Treat possible exceptions here
    oauth_token = await User.get_oauth_token(code)
    response = RedirectResponse(url=sep_settings.OAUTH.POST_LOGIN_URI)
    response.set_cookie(
        **sep_settings.SESSION.model_dump(by_alias=True),
        value=crypto_timestamp_serializer.dumps(oauth_token.access_token),
        httponly=True,
    )
    return response


@sep_app.post("/logout", dependencies=[IsAuthenticated])
async def logout(access_token: AccessTokenCookie) -> RedirectResponse:
    """Logout route."""
    # TODO: CSRF protection
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(sep_settings.SESSION.COOKIE_NAME)
    try:
        await User.invalidate_oauth_token(access_token)
    except (KeyError, InvalidTokenError, ValidationError):
        logger.debug("Failed to invalidate OAuth token", exc_info=True)
    return response


@sep_app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, context: DefaultContext) -> HTMLResponse:
    """Homepage route."""
    return templates.TemplateResponse(
        request=request,
        name="homepage.html",
        context=context,
    )


# TODO: take all these logics from routes layer

if __name__ == "__main__":
    # TODO: Rich formatting and custom logging handlers
    logging.basicConfig(
        level=sep_settings.LOGGING,
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> "
        "%(module)s.%(funcName)s - %(message)s",
    )
    logging.getLogger("sqlalchemy.engine").setLevel(settings.SQLALCHEMY_LOGGING)

    import uvicorn

    uvicorn.run(
        sep_app,
        host=sep_settings.UVICORN_HOST,
        port=sep_settings.UVICORN_PORT,
        proxy_headers=sep_settings.PROXY_HEADERS,
        ssl_keyfile=sep_settings.SSL_KEYFILE,
        ssl_certfile=sep_settings.SSL_CERTFILE,
    )
