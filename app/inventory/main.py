"""Define Inventory routes."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.inventory.config import inventory_settings
from app.inventory.routes import router

logger = logging.getLogger(__name__)

inventory_app = FastAPI()
inventory_app.include_router(router)


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
    # TODO: Rich formatting and custom logging handlers
    logging.basicConfig(
        level=settings.LOGGING,
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> "
        "%(module)s.%(funcName)s - %(message)s",
    )
    import uvicorn

    uvicorn.run(
        inventory_app,
        host=inventory_settings.INVENTORY_ENDPOINT.host,
        port=inventory_settings.INVENTORY_ENDPOINT.port,
        ssl_keyfile=inventory_settings.INVENTORY_SSL_KEYFILE,
        ssl_certfile=inventory_settings.INVENTORY_SSL_CERTFILE,
    )
