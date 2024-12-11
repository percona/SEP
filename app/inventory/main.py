"""Define Inventory routes."""

import logging.config

from fastapi import APIRouter

from app.api.deps import IsAuthenticatedDep
from app.core.config import create_app, default_lifespan, settings
from app.inventory.config import inventory_settings
from app.inventory.crud import NodeManager, SchemaManager, ServiceManager
from app.inventory.deps import SessionDep
from app.inventory.models import SummaryResponse
from app.inventory.routes import nodes, schemas, services, tables

summary_router = APIRouter(prefix="/summary", tags=["summary"])


@summary_router.get("/", dependencies=[IsAuthenticatedDep])
async def get_summary_inventory(session: SessionDep) -> SummaryResponse:
    """Retrieve a summary of inventory counts."""
    nodes = await NodeManager.list(session=session)
    services = await ServiceManager.list(session=session)
    schemas = await SchemaManager.list(session=session)
    tables = await ServiceManager.list(session=session)
    return SummaryResponse(
        nodes=len(nodes),
        services=len(services),
        schemas=len(schemas),
        tables=len(tables),
    )


lifespan = default_lifespan if __name__ == "__main__" else None
inventory_app = create_app(
    summary_router,
    nodes.router,
    services.router,
    schemas.router,
    tables.router,
    lifespan=lifespan,
    add_cors_middleware=True,
)


if __name__ == "__main__":
    logging.config.dictConfig(settings.LOGGING_CONFIG)

    import uvicorn

    uvicorn.run(
        inventory_app,
        host=inventory_settings.UVICORN_HOST,
        port=inventory_settings.UVICORN_PORT,
        ssl_keyfile=inventory_settings.SSL_KEYFILE,
        ssl_certfile=inventory_settings.SSL_CERTFILE,
        log_config=settings.LOGGING_CONFIG,
    )
