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

"""Define the main FastAPI app."""

import functools
import logging.config
from argparse import ArgumentParser
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from multiprocessing import Process
from typing import Any

from fastapi import FastAPI, Response, status
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from app import __summary__, __version__
from app.api.main import api_router
from app.celery import celery as celery_app
from app.core.auth.config import detect_removed_auth_user_model
from app.core.config import (
    create_app,
    detect_removed_settings_override_keys,
    settings,
)
from app.core.middleware.log_context import LogContextMiddleware
from app.core.utils import validate_importable_settings
from app.core.utils.openapi import merge_openapi_documents
from app.inventory.main import inventory_app, inventory_overrides_lifespan
from app.sep.apps.framework.registry import build_celery_include
from app.sep.config import sep_settings
from app.sep.main import sep_app, sep_overrides_lifespan, sep_startup
from app.tasks.main import tasks_app, tasks_lifespan


@asynccontextmanager
async def main_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage the app's lifespan.

    Initializes the Tasks database data, the periodic tasks data, and ensures that the
    active auth provider's SDK, the NomadExecutor, and any extra client sessions are
    properly managed during the application's startup and shutdown phases.

    Starlette's ``Mount`` never forwards ``lifespan`` scope to the mounted
    ``sep_app``/``inventory_app``, so their override refreshers are entered here
    (alongside ``tasks_lifespan``) rather than from their own lifespans. Only
    ``tasks_lifespan`` enters :func:`app.core.config.default_lifespan`, so the
    shared ``settings.CASDOOR`` / client registry is entered exactly once.

    :param app: The FastAPI application instance.
    :yield: None
    """
    detect_removed_auth_user_model()
    detect_removed_settings_override_keys()
    validate_importable_settings(*(s.syncer for s in sep_settings.SYNCERS))
    await sep_startup()
    async with (
        sep_overrides_lifespan(app),
        tasks_lifespan(app),
        inventory_overrides_lifespan(app),
    ):
        yield


app = create_app(
    api_router,
    lifespan=main_lifespan,
    backend_cors_origins=sep_settings.BACKEND_CORS_ORIGINS,
    allowed_hosts=sep_settings.ALLOWED_HOSTS,
    security_headers=sep_settings.SECURITY_HEADERS,
    title="SEP HTTP API",
    version=__version__,
    description=(
        f"{__summary__}\n\n"
        "This spec is the **core** API only (OAuth, users). Mounted services publish "
        "separate OpenAPI JSON on the same host: "
        "``/api/inventory/openapi.json``, ``/api/tasks/openapi.json``, and "
        "``/api/sep/openapi.json`` (the SEP web app: ``sep_app`` — shared routes, "
        "plugins, etc.; not merged into this document)."
    ),
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(LogContextMiddleware)


@app.get(
    "/api/sep/openapi.json",
    tags=["sep"],
    summary="SEP web application OpenAPI schema",
    response_model=None,
    include_in_schema=False,
)
def sep_openapi_json() -> JSONResponse:
    """Return the OpenAPI document for the SEP web application (``sep_app``).

    Same pattern as the mounted Inventory and Tasks apps (each exposes its own
    ``/api/.../openapi.json``; the top-level ``/openapi.json`` on this app remains the
    core API only and does not merge other sub-applications).

    :return: The OpenAPI 3.x JSON schema produced by ``sep_app.openapi()``.
    :rtype: JSONResponse
    """
    return JSONResponse(sep_app.openapi())


@functools.lru_cache(maxsize=1)
def _get_merged_openapi() -> dict[str, Any]:
    """Return the merged OpenAPI document, computed once and cached for the process.

    FastAPI's own ``app.openapi_schema`` cache fixes the upstream specs after the
    first hit, and routes are not added at runtime, so a single-entry cache is safe.

    :return: The merged OpenAPI 3.x JSON document.
    :rtype: dict[str, Any]
    """
    return merge_openapi_documents(app.openapi(), sep_app.openapi())


@app.get(
    "/api/openapi.json",
    tags=["sep"],
    summary="Unified public OpenAPI schema (core + SEP web app)",
    response_model=None,
    include_in_schema=False,
)
def merged_openapi_json() -> JSONResponse:
    """Return the merged OpenAPI document for the public ``/api/*`` surface.

    Unions the core API spec (``app.openapi()``) with the SEP web app spec
    (``sep_app.openapi()``) via
    :func:`app.core.utils.openapi.merge_openapi_documents`. The two upstream specs
    at ``/openapi.json`` and ``/api/sep/openapi.json`` are unchanged — they remain
    the source of truth for the React frontend's ``openapi-typescript`` codegen.

    :return: The merged OpenAPI 3.x JSON document.
    :rtype: JSONResponse
    """
    return JSONResponse(_get_merged_openapi())


@app.get(
    "/api/docs",
    tags=["sep"],
    summary="Swagger UI for the unified SEP public API",
    response_model=None,
    include_in_schema=False,
)
def merged_swagger_ui() -> HTMLResponse:
    """Return Swagger UI HTML pointing at the unified ``/api/openapi.json``."""
    return get_swagger_ui_html(
        openapi_url="/api/openapi.json",
        title="SEP Public API - Swagger UI",
    )


@app.get("/docs", include_in_schema=False)
@app.get("/redoc", include_in_schema=False)
def _disabled_top_level_docs() -> Response:
    """Reject ``/docs`` and ``/redoc`` with a 404.

    The auto-generated Swagger UI on the top-level app is disabled (see
    ``docs_url=None`` / ``redoc_url=None`` on ``create_app``).  Use ``/api/docs``
    instead.

    These explicit handlers must stay registered because ``sep_app`` keeps
    FastAPI's default ``docs_url="/docs"`` and ``redoc_url="/redoc"`` so it
    remains self-describing in standalone use.  Without these routes the
    ``sep_app`` mount at ``/`` would answer ``/docs`` and ``/redoc`` with its own
    partial spec — and those paths are not in the CSP exemption list
    (``SECURITY_HEADERS.CONTENT_SECURITY_POLICY_EXCLUDE_PATHS``), so the pages
    would render broken.  By registering these 404 handlers before
    ``app.mount("/", sep_app)``, mount-order precedence ensures the top-level app
    wins and returns a clean 404.
    """
    return Response(status_code=status.HTTP_404_NOT_FOUND)


app.mount("/api/inventory", inventory_app)
app.mount("/api/tasks", tasks_app)
app.mount("/", sep_app)


def start_celery_worker() -> None:
    """Start the Celery worker process."""
    worker = celery_app.Worker(include=build_celery_include())
    worker.start()


def start_celery_beat() -> None:
    """Start the Celery beat process."""
    beat = celery_app.Beat(
        scheduler="sqlalchemy",
        loglevel=settings.LOGGING_CONFIG["loggers"]["celery.beat"]["level"],
    )
    beat.run()


if __name__ == "__main__":
    import uvicorn

    parser = ArgumentParser()
    parser.add_argument(
        "--start-celery",
        action="store_true",
        default=False,
        help="Start the celery worker and beat processes",
    )
    args = parser.parse_args()

    if args.start_celery:
        logging.config.dictConfig(settings.LOGGING_CONFIG)

        celery_worker_process = Process(target=start_celery_worker)
        logging.info("Starting Celery worker...")
        celery_worker_process.start()

        celery_beat_process = Process(target=start_celery_beat)
        logging.info("Starting Celery beat for periodic tasks...")
        celery_beat_process.start()

        try:
            uvicorn.run(
                "app.main:app",
                host=sep_settings.UVICORN_HOST,
                port=sep_settings.UVICORN_PORT,
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
        except KeyboardInterrupt:
            logging.info("Shutting down Celery worker...")
            logging.info("Shutting down Celery beat...")
        finally:
            celery_worker_process.terminate()
            celery_worker_process.join()
            celery_beat_process.terminate()
            celery_beat_process.join()

    else:
        logging.config.dictConfig(settings.LOGGING_CONFIG)
        uvicorn.run(
            "app.main:app",
            host=sep_settings.UVICORN_HOST,
            port=sep_settings.UVICORN_PORT,
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
