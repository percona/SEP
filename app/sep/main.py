"""Define SEP routes."""

import logging
from importlib import import_module

from fastapi import FastAPI
from fastapi import Request
from fastapi import status
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from app.core.auth.utils import get_user_model
from app.core.config import settings
from app.sep.config import sep_settings
from app.sep.deps import DefaultContext
from app.sep.deps import get_current_user
from app.sep.deps import get_default_context
from app.sep.deps import IsAuthenticatedCookie

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


# TODO: take all these logics from routes layer

if __name__ == "__main__":
    # TODO: Rich formatting and custom logging handlers
    logging.basicConfig(
        level=settings.LOGGING,
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> "
        "%(module)s.%(funcName)s - %(message)s",
    )
    import uvicorn

    uvicorn.run(
        sep_app,
        host=sep_settings.SEP_ENDPOINT.host,
        port=sep_settings.SEP_ENDPOINT.port,
    )
