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

"""Define Inventory routes."""

import logging.config

from fastapi import APIRouter, Request, status

from app.api.deps import IsAuthenticatedDep
from app.core.config import create_app, default_lifespan, settings
from app.inventory.config import inventory_settings
from app.inventory.crud import NodeManager, SchemaManager, ServiceManager, TableManager
from app.inventory.deps import SessionDep
from app.inventory.routes import nodes, schemas, services, tables

logger = logging.getLogger(__name__)

summary_router = APIRouter(prefix="/summary", tags=["summary"])


@summary_router.get("/", dependencies=[IsAuthenticatedDep])
async def get_summary_inventory(session: SessionDep) -> dict[str, int]:
    """Retrieve a summary of inventory counts."""
    nodes = await NodeManager.count(session=session)
    services = await ServiceManager.count(session=session)
    schemas = await SchemaManager.count(session=session)
    tables = await TableManager.count(session=session)
    return {
        "nodes": nodes,
        "services": services,
        "schemas": schemas,
        "tables": tables,
    }


lifespan = default_lifespan if __name__ == "__main__" else None
inventory_app = create_app(
    summary_router,
    nodes.router,
    services.router,
    schemas.router,
    tables.router,
    lifespan=lifespan,
    backend_cors_origins=inventory_settings.BACKEND_CORS_ORIGINS,
    allowed_hosts=inventory_settings.ALLOWED_HOSTS,
    security_headers=inventory_settings.SECURITY_HEADERS,
)


@inventory_app.exception_handler(status.HTTP_500_INTERNAL_SERVER_ERROR)
async def internal_error_handler(
    _: Request,
    exc: BaseException,
) -> None:
    """Proper log unhandled exceptions."""
    logger.exception("Unhandled exception:", exc_info=exc)
    raise exc


if __name__ == "__main__":
    logging.config.dictConfig(settings.LOGGING_CONFIG)

    import uvicorn

    uvicorn.run(
        "app.inventory.main:inventory_app",
        host=inventory_settings.UVICORN_HOST,
        port=inventory_settings.UVICORN_PORT,
        ssl_keyfile=inventory_settings.SSL_KEYFILE,
        ssl_certfile=inventory_settings.SSL_CERTFILE,
        log_config=settings.LOGGING_CONFIG,
        reload=True,
        reload_dirs=[str(settings.BASE_DIR), str(settings.BASE_DIR / "app")],
        reload_includes=[f"{settings.BASE_DIR.name}/settings.yaml"],
        reload_excludes=[f"{settings.BASE_DIR.name}/*.py"],
    )
