"""Define Inventory routes."""

import logging.config

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
    allowed_hosts=inventory_settings.ALLOWED_HOSTS,
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
