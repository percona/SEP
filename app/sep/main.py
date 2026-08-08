# Copyright (C) 2026 Percona LLC
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
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from copy import deepcopy
from traceback import format_exception
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import HttpUrl, ValidationError
from starlette.staticfiles import StaticFiles

from app import __summary__, __version__
from app.api.main import api_router as top_level_api_router
from app.core.auth import config as auth_config
from app.core.auth.exceptions import BaseAuthProviderException
from app.core.auth.utils import get_user_model
from app.core.celery.utils import init_periodic_tasks_db
from app.core.config import create_app, default_lifespan, settings
from app.core.exceptions import HTTPBadGatewayException, HTTPServiceUnavailableException
from app.core.health import build_health_router
from app.core.requests import RemoteAPI
from app.core.security import crypto_timestamp_serializer
from app.core.settings_override.lifecycle import (
    RefreshCallback,
    settings_override_refresher,
)
from app.core.settings_override.models import SettingClassEnum
from app.core.utils import run_pydantic_type_validator
from app.core.utils.fields import URIPath
from app.inventory.config import inventory_settings
from app.sep.api.router import api_router
from app.sep.apps.framework.registry import (
    get_app_registry,
)
from app.sep.config import sep_settings
from app.sep.db import get_async_session_maker
from app.sep.db.seed import get_system_periodic_tasks, init_sep_db
from app.sep.deps import (
    AccessTokenCookie,
    get_base_url,
    get_current_user,
    get_default_context,
    get_tasks_index_context,
    is_bearer_authenticated,
    IsAuthenticated,
    IsCsrfValidated,
    IsNotAuthenticated,
    PROTECTED_APP_KEYS,
    require_app_enabled,
    resolve_ambient_session_token,
)
from app.sep.exceptions import LoginRedirectException
from app.sep.middleware import CSRFMiddleware, messages
from app.sep.middleware.csrf import CSRF_COOKIE_NAME
from app.sep.middleware.messages.config import messages_settings
from app.sep.settings_override import (
    build_sep_override_proxies,
    invalidate_pmm_clients,
)
from app.sep.snippets.celery import sync_snippets
from app.sep.snippets.config import snippets_settings
from app.sep.utils.static import AuthenticatedStaticFiles
from app.tasks.config import tasks_settings

logger = logging.getLogger(__name__)

JSON_API_PATH_PREFIXES: tuple[str, ...] = (
    "/api/sep/",
    "/api/admin/",
    "/api/apps/",
)


def warn_if_ambient_sso_inert() -> None:
    """Emit a warning when ambient SSO is enabled but the active provider can't honor it.

    Catch the static (env/YAML) misconfiguration at startup; the admin-UI
    applicability toggle covers the live case. Advisory only -- the runtime
    resolver no-ops regardless.
    """
    if (
        sep_settings.AMBIENT_SESSION_SSO_ENABLED
        and not auth_config.get_active_auth_provider().supports_ambient_session
    ):
        logger.warning(
            "AMBIENT_SESSION_SSO_ENABLED is on but the active auth provider does "
            "not support ambient sessions; ambient auto-login will not occur."
        )


async def sep_startup() -> None:
    """Define actions to perform on SEP startup.

    Initialize the SEP periodic task database, trigger the initial snippets
    synchronization if configured, and warn when ambient SSO is enabled under a
    provider that cannot honor it.
    """
    await init_sep_db()
    if snippets_settings.SYNC_ON_STARTUP:
        sync_snippets.delay()
    warn_if_ambient_sso_inert()


def _make_remote_api_rebinder(
    app: FastAPI,
    name: str,
    endpoint_getter: Callable[[], HttpUrl],
    **ssl: Any,
) -> RefreshCallback:
    """Build a rebind callback for an ``app.state`` RemoteAPI endpoint override.

    The returned callback handles both deployment shapes. Under standalone
    ``sep_lifespan`` the client lives in ``app.state.<name>``: it is rebuilt on
    the new endpoint and the old one closed. Under the combined ``app.main:app``
    no ``app.state`` client exists -- ``get_*_client`` falls back to the
    registry-cached ``get_remote_api`` per request, which already key-misses to
    the new HOT endpoint -- so the callback only evicts any stale client left on
    the new endpoint.

    :param app: The FastAPI application whose ``state`` holds the client.
    :type app: FastAPI
    :param name: The ``app.state`` attribute name (``inventory_api`` /
        ``tasks_api``).
    :type name: str
    :param endpoint_getter: A zero-argument callable returning the current
        (override-aware) endpoint.
    :type endpoint_getter: Callable[[], HttpUrl]
    :param ssl: SSL keyword arguments forwarded to :class:`RemoteAPI` (not HOT,
        captured once at wiring time).
    :type ssl: Any
    :return: The rebind callback.
    :rtype: RefreshCallback
    """

    async def _rebind(_: Mapping[str, object]) -> None:
        new_endpoint = endpoint_getter()
        old = getattr(app.state, name, None)
        if old is None:
            await settings.invalidate_client(str(new_endpoint))
            return
        try:
            new_api = await RemoteAPI(endpoint=new_endpoint, **ssl).open()
        except Exception:
            logger.exception("Failed to rebind %s; keeping previous client", name)
            return
        setattr(app.state, name, new_api)
        await old.__aexit__(None, None, None)

    return _rebind


async def _apply_logging_dictconfig(_: Mapping[str, object]) -> None:
    """Re-apply ``logging.config.dictConfig`` after a global ``LOGGING`` override.

    ``LOGGING`` is a HOT field, but ``LOGGING_CONFIG`` (the dict handed to
    ``dictConfig``) is not: the override snapshot replaces only the ``LOGGING``
    key, so ``settings.LOGGING_CONFIG`` still carries the level baked in by the
    ``set_log_level`` model validator at construction time. This callback mirrors
    that validator -- inject the now-live ``settings.LOGGING`` into a copy of the
    config and re-apply it -- so a log-level change takes effect in the SEP web
    process without a restart. Failures are logged and swallowed: a malformed
    config must not take the process down mid-request.

    :param _: The new effective ``Settings`` snapshot mapping (unused -- the level
        is re-read from the proxy).
    """
    try:
        config = deepcopy(settings.LOGGING_CONFIG)
        config["loggers"][""]["level"] = settings.LOGGING
        config["loggers"]["app"]["level"] = settings.LOGGING
        logging.config.dictConfig(config)
    except Exception:
        logger.exception("Failed to re-apply logging config after LOGGING override")


async def _reseed_system_periodic_tasks(_: Mapping[str, object]) -> None:
    """Re-seed the SEP beat schedule after a hot interval override.

    Wired for both ``SnippetsSettings.SYNC_INTERVAL`` (``sep__sync_snippets``) and
    ``AlertsSettings.BACKUP_INTERVAL`` (``sep__backup_alert_config``). Rebuilds the
    system periodic-task set via
    :func:`app.sep.db.seed.get_system_periodic_tasks` -- which re-reads the now-live
    interval from the refreshed proxy snapshot -- and re-invokes
    :func:`app.core.celery.utils.init_periodic_tasks_db` under the ``sep__`` prefix.
    The seeding is idempotent (get-or-create plus upsert by task name); its update
    path reassigns only ``task`` / ``schedule_model`` / extra kwargs, so the
    ``enabled`` gating state written by
    :func:`app.sep.periodic_tasks.sync_app_periodic_task_gating` is preserved.
    Updating the ``IntervalSchedule`` bumps ``PeriodicTaskChanged.last_update``, so
    Celery beat reloads the schedule on its next scheduler tick without a restart.

    :param _: The new effective settings snapshot mapping (unused -- the interval is
        re-read from the proxy by the task-set builder).
    """
    await init_periodic_tasks_db(get_system_periodic_tasks(), "sep__")


@asynccontextmanager
async def sep_overrides_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Wire the SEP-side settings override refresher into a lifespan.

    Force-resolves ``messages_settings`` (fail-fast validation), then starts the
    background refresher for the duration of the wrapped block over the proxy
    map :func:`build_sep_override_proxies` composes -- the shared set every SEP
    process refreshes, so no wiring drifts from another's.
    Endpoint and PMM rebind callbacks are built here -- where ``app`` is
    available -- so both run modes wire them.

    This is extracted from :func:`sep_lifespan` because ``sep_app`` is mounted
    under the top-level ``app`` via Starlette's ``Mount``, which only forwards
    ``http``/``websocket`` scopes -- never ``lifespan``. Without calling this
    context manager from :func:`app.main.main_lifespan`, the SEP refresher
    would never run when ``python -m app.main`` serves ``app.main:app``.

    The two call sites are mutually exclusive at runtime: uvicorn serves
    either ``app.main:app`` (in which case ``main_lifespan`` enters this
    block) or ``app.sep.main:sep_app`` standalone (in which case
    ``sep_lifespan`` enters it). The refresher therefore starts exactly once.

    :param app: The FastAPI application instance, used to wire endpoint rebind
        callbacks against ``app.state``.
    :return: None
    """
    # Force-resolve ``messages_settings`` so the proxy's underlying Pydantic
    # instance is constructed (and validated) before any lifespan side
    # effects (DB init, snippet sync enqueue) can fire. Mirrors the previous
    # eager ``MessagesSettings()`` fail-fast behavior at import time.
    messages_settings._resolve()  # noqa: SLF001
    callbacks = {
        (
            SettingClassEnum.SEP_SETTINGS,
            "INVENTORY_ENDPOINT",
        ): _make_remote_api_rebinder(
            app,
            "inventory_api",
            lambda: sep_settings.INVENTORY_ENDPOINT,
            ssl_cafile=settings.SSL_CAFILE,
            ssl_keyfile=inventory_settings.SSL_KEYFILE,
            ssl_certfile=inventory_settings.SSL_CERTFILE,
        ),
        (SettingClassEnum.SEP_SETTINGS, "TASKS_ENDPOINT"): _make_remote_api_rebinder(
            app,
            "tasks_api",
            lambda: sep_settings.TASKS_ENDPOINT,
            ssl_cafile=settings.SSL_CAFILE,
            ssl_keyfile=tasks_settings.SSL_KEYFILE,
            ssl_certfile=tasks_settings.SSL_CERTFILE,
        ),
        (SettingClassEnum.SETTINGS, "PMM"): invalidate_pmm_clients,
        (SettingClassEnum.SETTINGS, "LOGGING"): _apply_logging_dictconfig,
        (
            SettingClassEnum.SNIPPETS_SETTINGS,
            "SYNC_INTERVAL",
        ): _reseed_system_periodic_tasks,
        (
            SettingClassEnum.ALERTS_SETTINGS,
            "BACKUP_INTERVAL",
        ): _reseed_system_periodic_tasks,
        (
            SettingClassEnum.SEP_SETTINGS,
            "APP_DRAIN",
        ): _reseed_system_periodic_tasks,
    }
    # On ``sep_app``'s state, not the lifespan's parent ``app``: requests to
    # ``/api/sep/...`` resolve ``request.app`` to the mounted ``sep_app``, where
    # the settings-API handlers read it.
    sep_app.state.override_callbacks = callbacks
    async with settings_override_refresher(
        get_async_session_maker,
        build_sep_override_proxies(),
        callbacks=callbacks,
    ):
        yield


@asynccontextmanager
async def sep_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage SEP's lifespan.

    Initializes the SEP periodic task database and the RemoteAPI clients for
    inventory and tasks services, ensuring they are properly managed during the
    application's startup and shutdown phases. The override refresher publishes
    its initial snapshot *before* the ``app.state`` clients are constructed, so
    they read the effective (override-aware) endpoint; because the initial
    refresh fires no callbacks, the endpoint rebinders never dereference
    not-yet-built ``app.state``.

    The clients are closed via ``app.state`` (not via the originals captured
    at startup) on shutdown, so a client a rebind callback swapped in mid-run is
    the one that gets closed -- the swapped-out original was already closed by
    the rebinder.

    :param app: The FastAPI application instance.
    :type app: FastAPI
    :yield: None
    :rtype: AsyncGenerator[None, None]
    """
    await sep_startup()
    async with sep_overrides_lifespan(app):
        app.state.inventory_api = await RemoteAPI(
            endpoint=sep_settings.INVENTORY_ENDPOINT,
            ssl_cafile=settings.SSL_CAFILE,
            ssl_keyfile=inventory_settings.SSL_KEYFILE,
            ssl_certfile=inventory_settings.SSL_CERTFILE,
        ).open()
        app.state.tasks_api = await RemoteAPI(
            endpoint=sep_settings.TASKS_ENDPOINT,
            ssl_cafile=settings.SSL_CAFILE,
            ssl_keyfile=tasks_settings.SSL_KEYFILE,
            ssl_certfile=tasks_settings.SSL_CERTFILE,
        ).open()
        try:
            async with default_lifespan(app):
                yield
        finally:
            await app.state.tasks_api.__aexit__(None, None, None)
            await app.state.inventory_api.__aexit__(None, None, None)


lifespan = sep_lifespan
sep_app = create_app(
    build_health_router(get_async_session_maker),
    lifespan=lifespan,
    allowed_hosts=sep_settings.ALLOWED_HOSTS,
    security_headers=sep_settings.SECURITY_HEADERS,
    title="SEP Web Application API",
    version=__version__,
    description=(
        f"{__summary__}\n\n"
        "Browser-oriented SEP routes (HTML, redirects, proxies, streams). "
        "JSON REST APIs for inventory and tasks live on the mounted sub-apps."
    ),
)
sep_app.add_middleware(CSRFMiddleware)
sep_app.add_middleware(messages.MessagesMiddleware)


jinja_ui_mounted = False
for app in get_app_registry():
    if app.jinja_router is None:
        continue
    plugin_deps = (
        []
        if app.state_key in PROTECTED_APP_KEYS
        else [Depends(require_app_enabled(app.key))]
    )
    sep_app.include_router(
        app.jinja_router, prefix=app.uri_path, dependencies=plugin_deps
    )
    jinja_ui_mounted = True

if any(app.uses_task_data for app in get_app_registry()):
    from app.sep.routes.download_files import router as download_files_router
    from app.sep.routes.execution_events import router as execution_events_router
    from app.sep.routes.stream_logs import router as stream_logs_router

    sep_app.include_router(stream_logs_router, prefix="/stream-logs")
    sep_app.include_router(download_files_router, prefix="/files")
    sep_app.include_router(execution_events_router, prefix="/execution-events")

if jinja_ui_mounted:
    from app.sep.routes.inventory_ajax import router as inventory_ajax_router
    from app.sep.routes.periodic_tasks import router as periodic_tasks_router
    from app.sep.routes.stop_task import router as stop_task_router

    sep_app.include_router(inventory_ajax_router, prefix="/inventory-api")
    sep_app.include_router(stop_task_router, prefix="/stop-task")
    sep_app.include_router(periodic_tasks_router, prefix="/periodic")

if any(app.artifact_base_dirs for app in get_app_registry()):
    from app.sep.routes.artifacts import router as artifacts_router

    sep_app.include_router(artifacts_router, prefix="/artifacts")

sep_app.include_router(api_router)
sep_app.include_router(top_level_api_router, include_in_schema=False)

for app in get_app_registry():
    for static_mount in app.static_mounts:
        sep_app.mount(
            static_mount.path,
            AuthenticatedStaticFiles(directory=static_mount.directory),
            name=static_mount.name,
        )
sep_app.mount("/static", StaticFiles(directory=sep_settings.STATIC_DIR), name="static")

User = get_user_model()
templates = sep_settings.TEMPLATES


@sep_app.exception_handler(status.HTTP_500_INTERNAL_SERVER_ERROR)
async def internal_error_handler(
    request: Request,
    exc: BaseException,
) -> HTMLResponse | JSONResponse | RedirectResponse:
    """Load custom error page."""
    logger.exception("Unhandled exception:", exc_info=exc)
    if request.url.path.startswith(JSON_API_PATH_PREFIXES):
        return JSONResponse(
            {"detail": "Internal Server Error"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    base_url = get_base_url(request)
    try:
        user = await get_current_user(request)
    except LoginRedirectException as redirect_exc:
        return RedirectResponse(
            redirect_exc.location,
            status_code=redirect_exc.status_code,
            headers=redirect_exc.headers,
        )
    messages.error(
        request,
        "Internal Server Error. Please contact the administrators for help.",
        sticky=True,
    )
    async with get_async_session_maker()() as session:
        default_context = await get_default_context(request, user, base_url, session)
    return templates.TemplateResponse(
        request=request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        name="error.html.j2",
        context={
            "exception": "".join(format_exception(exc, limit=-1, chain=False)),
            **default_context,
        },
    )


@sep_app.exception_handler(status.HTTP_404_NOT_FOUND)
async def custom_404_handler(
    request: Request,
    exc: BaseException,
) -> Response:
    """Load custom 404 page."""
    if request.url.path.startswith(JSON_API_PATH_PREFIXES):
        detail = getattr(exc, "detail", "Not Found")
        headers = getattr(exc, "headers", None)
        return JSONResponse(
            {"detail": detail},
            status_code=status.HTTP_404_NOT_FOUND,
            headers=headers,
        )

    base_url = get_base_url(request)
    try:
        user = await get_current_user(request)
    except LoginRedirectException as redirect_exc:
        return RedirectResponse(
            redirect_exc.location,
            status_code=redirect_exc.status_code,
            headers=redirect_exc.headers,
        )
    async with get_async_session_maker()() as session:
        default_context = await get_default_context(request, user, base_url, session)
    return templates.TemplateResponse(
        request=request,
        status_code=status.HTTP_404_NOT_FOUND,
        name="404.html.j2",
        context={
            "exception": exc,
            **default_context,
        },
    )


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


@sep_app.exception_handler(HTTPServiceUnavailableException)
@sep_app.exception_handler(HTTPBadGatewayException)
async def json_exception_handler(
    request: Request,  # noqa: ARG001
    exc: HTTPException,
) -> JSONResponse:
    """Return a JSON error response for server-side gateway exceptions.

    :param request: The incoming request.
    :type request: Request
    :param exc: The HTTP exception to handle.
    :type exc: HTTPException
    :return: A JSON response with the error detail and status code.
    :rtype: JSONResponse
    """
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers,
    )


@sep_app.exception_handler(HTTPException)
async def default_exception_handler(request: Request, exc: HTTPException) -> Response:
    """Define default exception handler."""
    if request.url.path.startswith(JSON_API_PATH_PREFIXES) or is_bearer_authenticated(
        request
    ):
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    error_detail = exc.detail
    messages.error(request, str(error_detail))
    return RedirectResponse(
        request.headers.get("referer", "/"), status_code=status.HTTP_303_SEE_OTHER
    )


@sep_app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    """Surface form-body validation errors as flash messages, not raw JSON.

    FastAPI's default :class:`RequestValidationError` handler returns a
    ``application/json`` 422 with a serialized error list, which the browser
    renders as a raw JSON blob via its built-in JSON viewer. That's fine for
    JSON API consumers but a poor UX for users submitting HTML forms — they
    end up staring at structured error JSON instead of returning to the form
    with an inline message.

    For non-API paths and session-authenticated requests we convert each
    validator failure into a flash message via :func:`messages.from_validation_error`
    and redirect back to the referer (the form page). ``none_required`` is
    excluded because every ``T | EmptyStrToNone``-shaped field produces a
    redundant ``none_required`` alongside the real validator failure when a
    non-empty value fails the ``T`` arm's constraint.
    """
    if request.url.path.startswith(JSON_API_PATH_PREFIXES) or is_bearer_authenticated(
        request
    ):
        return JSONResponse(
            {"detail": jsonable_encoder(exc.errors())},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    messages.from_validation_error(
        request,
        exc,
        "Validation error",
        exclude_types=("none_required",),
    )
    return RedirectResponse(
        request.headers.get("referer", "/"), status_code=status.HTTP_303_SEE_OTHER
    )


def _safe_next_path(next_path: str) -> str:
    r"""Validate a ``next`` redirect target, collapsing unsafe values to ``/``.

    Validate ``next_path`` as a same-origin ``URIPath`` so the password login and
    the ambient auto-login reject open-redirect targets identically. ``URIPath``
    alone still admits scheme-relative (``//host``) and backslash (``/\host``)
    targets that a browser follows off-origin, so also reject any value that a
    browser would resolve to a foreign host.

    :param next_path: The raw ``next`` query value.
    :return: The validated relative path, or ``/`` when ``next_path`` is not a
        safe same-origin path.
    """
    try:
        validated = run_pydantic_type_validator(URIPath, next_path)
    except ValidationError:
        return "/"
    if validated.startswith(("//", "/\\")) or urlsplit(validated).netloc:
        return "/"
    return validated


@sep_app.get(
    "/login",
    dependencies=[IsNotAuthenticated],
    include_in_schema=False,
    response_model=None,
)
async def login_form(
    request: Request, next_path: Annotated[str, Query(alias="next")] = "/"
) -> HTMLResponse | RedirectResponse:
    """Serve the login form, or auto-login from an ambient Grafana session.

    Attempt ambient Grafana SSO before rendering: on a valid ambient session,
    redirect to the sanitized ``next`` target with the SEP session cookie set;
    otherwise render the login form unchanged.

    :param request: The incoming request, carrying any ambient Grafana session
        cookie.
    :param next_path: The post-login redirect target (the ``next`` query param).
    :return: A redirect carrying the session cookie on ambient auto-login, else
        the rendered login form.
    """
    oauth_token = await resolve_ambient_session_token(request)
    if oauth_token is not None:
        response = RedirectResponse(
            _safe_next_path(next_path), status_code=status.HTTP_303_SEE_OTHER
        )
        response.set_cookie(
            **sep_settings.SESSION.model_dump(by_alias=True),
            value=crypto_timestamp_serializer.dumps(oauth_token.access_token),
            httponly=True,
        )
        response.delete_cookie(CSRF_COOKIE_NAME)
        return response
    return templates.TemplateResponse(
        request=request,
        name="login.html.j2",
        context={
            "csrf_token": request.state.csrf_token,
            "next_path": next_path,
        },
    )


@sep_app.post(
    "/login",
    dependencies=[IsNotAuthenticated, IsCsrfValidated],
    include_in_schema=False,
)
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
    response = RedirectResponse(
        _safe_next_path(next_path), status_code=status.HTTP_303_SEE_OTHER
    )
    response.set_cookie(
        **sep_settings.SESSION.model_dump(by_alias=True),
        value=crypto_timestamp_serializer.dumps(oauth_token.access_token),
        httponly=True,
    )
    response.delete_cookie(CSRF_COOKIE_NAME)
    return response


@sep_app.post(
    "/logout", dependencies=[IsAuthenticated, IsCsrfValidated], include_in_schema=False
)
async def logout(access_token: AccessTokenCookie) -> RedirectResponse:
    """Logout route."""
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(sep_settings.SESSION.COOKIE_NAME)
    response.delete_cookie(CSRF_COOKIE_NAME)
    try:
        await User.invalidate_oauth_token(access_token)
    except (KeyError, ValidationError):
        logger.debug("Failed to invalidate OAuth token", exc_info=True)
    return response


@sep_app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def read_root(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_tasks_index_context)],
) -> HTMLResponse:
    """Homepage route."""
    return templates.TemplateResponse(
        request=request,
        name="homepage.html.j2",
        context=context,
    )


if __name__ == "__main__":
    logging.config.dictConfig(settings.LOGGING_CONFIG)

    import uvicorn

    uvicorn.run(
        "app.sep.main:sep_app",
        host=sep_settings.UVICORN_HOST,
        port=sep_settings.UVICORN_PORT,
        proxy_headers=sep_settings.PROXY_HEADERS,
        ssl_keyfile=sep_settings.SSL_KEYFILE,
        ssl_certfile=sep_settings.SSL_CERTFILE,
        log_config=settings.LOGGING_CONFIG,
        reload=sep_settings.UVICORN_RELOAD,
        reload_dirs=[
            str(settings.BASE_DIR),
            str(settings.BASE_DIR / "app"),
            *sep_settings.UVICORN_EXTRA_RELOAD_DIRS,
        ],
        reload_includes=[
            f"{settings.BASE_DIR.name}/settings.yaml",
            *sep_settings.UVICORN_EXTRA_RELOAD_INCLUDES,
        ],
        reload_excludes=[
            f"{settings.BASE_DIR.name}/*.py",
            *sep_settings.UVICORN_EXTRA_RELOAD_EXCLUDES,
        ],
    )
