"""Define Inventory routes."""

import logging

from app.core.config import create_app, default_lifespan, settings
from app.inventory.config import inventory_settings
from app.inventory.routes import nodes, schemas, services, tables

lifespan = default_lifespan if __name__ == "__main__" else None
inventory_app = create_app(
    nodes.router,
    services.router,
    schemas.router,
    tables.router,
    lifespan=lifespan,
    add_cors_middleware=True,
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
