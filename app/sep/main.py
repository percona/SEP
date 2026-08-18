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
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any, cast, Literal

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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
from app.core.settings_override.lifecycle import (
    previous_or_base,
    RefreshCallback,
    settings_override_refresher,
    SnapshotChange,
)
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.utils.fields import CredentialHttpUrl
from app.inventory.config import inventory_settings
from app.sep.api.router import api_router
from app.sep.apps.framework.registry import (
    get_app_registry,
)
from app.sep.config import sep_settings, warn_if_base_url_lacks_root_path
from app.sep.db import get_async_session_maker
from app.sep.db.seed import get_system_periodic_tasks, init_sep_db
from app.sep.settings_override import (
    build_sep_override_proxies,
    invalidate_pmm_clients,
)
from app.sep.snippets.celery import sync_snippets
from app.sep.snippets.config import snippets_settings
from app.tasks.config import tasks_settings

logger = logging.getLogger(__name__)


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


def warn_if_external_base_lacks_prefix() -> None:
    """Emit a warning when a configured external base URL omits the URL prefix.

    Catch the static (env/YAML) misconfiguration at startup; a hot
    ``SNIPPETS_BASE_URL`` override is checked where the URL is built. Advisory
    only: startup continues on a mismatch.
    """
    warn_if_base_url_lacks_root_path(settings.BASE_URL, "BASE_URL")
    warn_if_base_url_lacks_root_path(
        snippets_settings.SNIPPETS_BASE_URL, "SNIPPETS_BASE_URL"
    )


async def sep_startup() -> None:
    """Define actions to perform on SEP startup.

    Initialize the SEP periodic task database, trigger the initial snippets
    synchronization if configured, warn when ambient SSO is enabled under a
    provider that cannot honor it, and warn when a configured external base URL
    omits the URL prefix SEP is served under.
    """
    await init_sep_db()
    if snippets_settings.SYNC_ON_STARTUP:
        sync_snippets.delay()
    warn_if_ambient_sso_inert()
    warn_if_external_base_lacks_prefix()


def _make_remote_api_rebinder(
    app: FastAPI,
    name: str,
    proxy: OverridableSettingsProxy,
    key: Literal["INVENTORY_ENDPOINT", "TASKS_ENDPOINT"],
    **ssl: Any,
) -> RefreshCallback:
    """Build a rebind callback for an ``app.state`` RemoteAPI endpoint override.

    The returned callback handles both deployment shapes. Under standalone
    ``sep_lifespan`` the client lives in ``app.state.<name>``: it is rebuilt on
    the new endpoint and the old one closed. Under the combined ``app.main:app``
    no ``app.state`` client exists -- ``get_*_client`` falls back to the
    registry-cached ``get_remote_api`` per request, which already key-misses to
    the new HOT endpoint -- so the callback evicts the ordered de-duplicated set
    of previous-and-current endpoints (covering endpoint moves as well as
    same-endpoint credential/SSL changes). When ``key`` is absent from
    ``change.previous`` (override created), :func:`previous_or_base` supplies
    the YAML/env value from the proxy's wrapped instance.

    :param app: The FastAPI application whose ``state`` holds the client.
    :type app: FastAPI
    :param name: The ``app.state`` attribute name (``inventory_api`` /
        ``tasks_api``).
    :type name: str
    :param proxy: The overridable settings proxy that owns the endpoint field.
    :param key: The top-level snapshot key for the endpoint field.
    :param ssl: SSL keyword arguments forwarded to :class:`RemoteAPI` (not HOT,
        captured once at wiring time).
    :type ssl: Any
    :return: The rebind callback.
    :rtype: RefreshCallback
    """

    async def _rebind(change: SnapshotChange) -> None:
        new_endpoint = cast(CredentialHttpUrl, getattr(proxy, key))
        old = getattr(app.state, name, None)
        if old is None:
            previous_endpoint = previous_or_base(change, proxy, key)
            for endpoint in dict.fromkeys(
                str(ep) for ep in (previous_endpoint, new_endpoint) if ep is not None
            ):
                await settings.invalidate_client(endpoint)
            return
        try:
            new_api = await RemoteAPI(endpoint=new_endpoint, **ssl).open()
        except Exception:
            logger.exception("Failed to rebind %s; keeping previous client", name)
            return
        setattr(app.state, name, new_api)
        await old.__aexit__(None, None, None)

    return _rebind


async def _apply_logging_dictconfig(_: SnapshotChange) -> None:
    """Re-apply ``logging.config.dictConfig`` after a global ``LOGGING`` override.

    ``LOGGING`` is a HOT field, but ``LOGGING_CONFIG`` (the dict handed to
    ``dictConfig``) is not: the override snapshot replaces only the ``LOGGING``
    key, so ``settings.LOGGING_CONFIG`` still carries the level baked in by the
    ``set_log_level`` model validator at construction time. This callback mirrors
    that validator -- inject the now-live ``settings.LOGGING`` into a copy of the
    config and re-apply it -- so a log-level change takes effect in the SEP web
    process without a restart. Failures are logged and swallowed: a malformed
    config must not take the process down mid-request.

    :param _: The override snapshots on either side of the republish (unused --
        the level is re-read from the proxy).
    """
    try:
        config = deepcopy(settings.LOGGING_CONFIG)
        config["loggers"][""]["level"] = settings.LOGGING
        config["loggers"]["app"]["level"] = settings.LOGGING
        logging.config.dictConfig(config)
    except Exception:
        logger.exception("Failed to re-apply logging config after LOGGING override")


async def _reseed_system_periodic_tasks(_: SnapshotChange) -> None:
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

    :param _: The override snapshots on either side of the republish (unused -- the
        interval is re-read from the proxy by the task-set builder).
    """
    await init_periodic_tasks_db(get_system_periodic_tasks(), "sep__")


@asynccontextmanager
async def sep_overrides_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Wire the SEP-side settings override refresher into a lifespan.

    Start the background refresher for the duration of the wrapped block over
    the proxy map :func:`build_sep_override_proxies` composes, the shared set
    every SEP process refreshes, so no wiring drifts from another's.
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
    callbacks = {
        (
            SettingClassEnum.SEP_SETTINGS,
            "INVENTORY_ENDPOINT",
        ): _make_remote_api_rebinder(
            app,
            "inventory_api",
            sep_settings,
            "INVENTORY_ENDPOINT",
            ssl_cafile=settings.SSL_CAFILE,
            ssl_keyfile=inventory_settings.SSL_KEYFILE,
            ssl_certfile=inventory_settings.SSL_CERTFILE,
        ),
        (SettingClassEnum.SEP_SETTINGS, "TASKS_ENDPOINT"): _make_remote_api_rebinder(
            app,
            "tasks_api",
            sep_settings,
            "TASKS_ENDPOINT",
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
    root_path=sep_settings.ROOT_PATH,
    title="SEP Web Application API",
    version=__version__,
    description=(
        f"{__summary__}\n\n"
        "Browser-oriented SEP routes (proxies, streams, downloads). "
        "JSON REST APIs for inventory and tasks live on the mounted sub-apps."
    ),
)


if any(app.uses_task_data for app in get_app_registry()):
    from app.sep.routes.download_files import router as download_files_router
    from app.sep.routes.execution_events import router as execution_events_router
    from app.sep.routes.stream_logs import router as stream_logs_router

    sep_app.include_router(stream_logs_router, prefix="/stream-logs")
    sep_app.include_router(download_files_router, prefix="/files")
    sep_app.include_router(execution_events_router, prefix="/execution-events")

if any(app.artifact_base_dirs for app in get_app_registry()):
    from app.sep.routes.artifacts import router as artifacts_router

    sep_app.include_router(artifacts_router, prefix="/artifacts")

sep_app.include_router(api_router)
sep_app.include_router(top_level_api_router, include_in_schema=False)

User = get_user_model()


@sep_app.exception_handler(status.HTTP_500_INTERNAL_SERVER_ERROR)
async def internal_error_handler(
    request: Request,  # noqa: ARG001
    exc: BaseException,
) -> JSONResponse:
    """Return a JSON error response for unhandled server errors.

    :param request: The incoming request.
    :param exc: The unhandled exception.
    :return: A JSON response carrying a generic 500 detail.
    """
    logger.exception("Unhandled exception:", exc_info=exc)
    return JSONResponse(
        {"detail": "Internal Server Error"},
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


@sep_app.exception_handler(status.HTTP_404_NOT_FOUND)
async def custom_404_handler(
    request: Request,  # noqa: ARG001
    exc: BaseException,
) -> JSONResponse:
    """Return a JSON error response for unmatched routes.

    ``exc`` is a bare :class:`BaseException` because the handler is registered on
    a status code rather than an exception class, so ``detail`` and ``headers``
    are read defensively.

    :param request: The incoming request.
    :param exc: The exception that produced the 404.
    :return: A JSON response with the error detail.
    """
    return JSONResponse(
        {"detail": getattr(exc, "detail", "Not Found")},
        status_code=status.HTTP_404_NOT_FOUND,
        headers=getattr(exc, "headers", None),
    )


@sep_app.exception_handler(BaseAuthProviderException)
async def auth_provider_exception_handler(
    request: Request,  # noqa: ARG001
    exc: BaseAuthProviderException,
) -> JSONResponse:
    """Return a JSON error response for auth-provider failures.

    :param request: The incoming request.
    :param exc: The auth-provider exception to handle.
    :return: A JSON response with the error detail and status code.
    """
    logger.exception("Error connecting to auth provider:", exc_info=exc)
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers,
    )


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
async def default_exception_handler(
    request: Request,  # noqa: ARG001
    exc: HTTPException,
) -> JSONResponse:
    """Return a JSON error response for any otherwise-unhandled HTTP exception.

    :param request: The incoming request.
    :param exc: The HTTP exception to handle.
    :return: A JSON response with the error detail and status code.
    """
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers,
    )


@sep_app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,  # noqa: ARG001
    exc: RequestValidationError,
) -> JSONResponse:
    """Return the serialized validator failures as a JSON 422.

    :param request: The incoming request.
    :param exc: The request-validation error to handle.
    :return: A JSON response carrying the encoded error list.
    """
    return JSONResponse(
        {"detail": jsonable_encoder(exc.errors())},
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
