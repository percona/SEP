"""Define Inventory routes."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.inventory.config import inventory_settings
from app.inventory.routes import nodes, schemas, services, tables

logger = logging.getLogger(__name__)

inventory_app = FastAPI()
inventory_app.include_router(nodes.router, tags=["nodes"])
inventory_app.include_router(services.router, prefix="/services", tags=["services"])
inventory_app.include_router(schemas.router, prefix="/schemas", tags=["schemas"])
inventory_app.include_router(tables.router, prefix="/tables", tags=["tables"])


if settings.BACKEND_CORS_ORIGINS:
    inventory_app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            str(origin).strip("/") for origin in settings.BACKEND_CORS_ORIGINS
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

if __name__ == "__main__":
    # TODO: Rich formatting and custom logging handlers  # noqa: TD002, TD003
    logging.basicConfig(
        level=settings.LOGGING,
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> "
        "%(module)s.%(funcName)s - %(message)s",
    )
    for name, level in settings.LOGGING_EXTRA.items():
        logging.getLogger(name).setLevel(level)

    import uvicorn

    uvicorn.run(
        inventory_app,
        host=inventory_settings.UVICORN_HOST,
        port=inventory_settings.UVICORN_PORT,
        ssl_keyfile=inventory_settings.SSL_KEYFILE,
        ssl_certfile=inventory_settings.SSL_CERTFILE,
    )
