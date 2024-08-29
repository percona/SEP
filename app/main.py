"""Define the main FastAPI app."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.inventory.main import inventory_app
from app.sep.main import sep_app
from app.tasks.main import database_shutdown
from app.tasks.main import prepare_database
from app.tasks.main import tasks_app

casdoor_sdk = settings.CASDOOR.SDK

app = FastAPI()


@app.on_event("startup")
async def startup():
    await prepare_database()


@app.on_event("shutdown")
async def shutdown():
    await database_shutdown()


if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            str(origin).strip("/") for origin in settings.BACKEND_CORS_ORIGINS
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.include_router(api_router, prefix="/api")
app.mount("/api/inventory", inventory_app)
app.mount("/api/tasks", tasks_app)
app.mount("/", sep_app)


if __name__ == "__main__":
    # TODO: Rich formatting and custom logging handlers
    logging.basicConfig(
        level=settings.LOGGING,
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> "
        "%(module)s.%(funcName)s - %(message)s",
    )
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
