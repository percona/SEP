"""Tasks API"""

import json
import logging
from collections import namedtuple
from os import getenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import event
from sqlalchemy.engine import Engine

import app.core.db
from app.core.config import settings
from app.tasks.config import tasks_settings
from app.tasks.models import history
from app.tasks.models import Task
from app.tasks.models import TASK_BACKEND_MAP
from app.tasks.models import tasks
from app.tasks.routes import router

logger = logging.getLogger(__name__)


DEFAULT_BACKEND_POLL_INTERVAL_SECONDS = 5
DEFAULT_DATABASE_DSN = f"{app.core.db.DEFAULT_DATABASE_DSN}/tasks.db"
DEFAULT_EXECUTION_MODE = "background"
DEFAULT_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000"

BACKEND_POLL_INTERVAL_SECONDS = getenv(
    "TASKS_BACKEND_POLL_INTERVAL_SECONDS",
    DEFAULT_BACKEND_POLL_INTERVAL_SECONDS,
)
DATABASE_URL = getenv("TASKS_DATABASE_URL", DEFAULT_DATABASE_DSN)
ORIGINS = getenv("TASKS_ORIGINS", DEFAULT_ORIGINS).split(",")

GENERIC_NOMAD_BATCH_TEMPLATE = {
    "ID": "generic-nomad-batch",
    "Name": "generic-nomad-batch",
    "Type": "batch",
    "Datacenters": ["dc1"],
    "Constraints": [
        {
            "LTarget": "${node.unique.name}",
            "RTarget": "valid_node_required",
            "Operand": "=",
        },
    ],
    "Periodic": None,
    "TaskGroups": [
        {
            "Name": "execution",
            "Tasks": [
                {
                    "Name": "generic-task",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "args": [],
                        "command": "",
                    },
                    "Meta": {},
                    "Restart": {"attempts": 0, "mode": "fail"},
                    "Templates": [],
                },
            ],
        },
    ],
}

GENERIC_NOMAD_SYSBATCH_TEMPLATE = {
    "ID": "generic-nomad-sysbatch",
    "Name": "generic-nomad-sysbatch",
    "Type": "sysbatch",
    "Datacenters": ["dc1"],
    "Periodic": None,
    "TaskGroups": [
        {
            "Name": "execution",
            "Tasks": [
                {
                    "Name": "generic-task",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "args": [],
                        "command": "",
                    },
                    "Meta": {},
                    "Restart": {"attempts": 0, "mode": "fail"},
                    "Templates": [],
                },
            ],
        },
    ],
}

TaskOwner = namedtuple("TaskOwner", ["value", "label"])
TranslateConfig = namedtuple("TranslateConfig", ["old", "new", "action"])

DEFAULT_BACKEND_ADDRESS = "http://127.0.0.1:8182"

TEMPLATE_PREFIX = "tasks"
TRANSLATION_MAPPING = {
    "create": (
        TranslateConfig("owners", "meta", "update"),
        TranslateConfig("taskalias", "name", "flatten"),
        TranslateConfig("taskdef", "data", "backend"),
        TranslateConfig("taskeng", "engine", "flatten"),
    ),
    "owners": (
        TaskOwner("*", "Any"),
        TaskOwner("archiver", "Data Archiver"),
        TaskOwner("alter", "Schema Change"),
    ),
}

database = app.core.db.get_database(DATABASE_URL, include_engine=True)

tasks_app = FastAPI()
tasks_app.include_router(router)
tasks_app.log = logger

if settings.BACKEND_CORS_ORIGINS:
    tasks_app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            str(origin).strip("/") for origin in settings.BACKEND_CORS_ORIGINS
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


async def prepare_database():
    """Prepare the database and application"""
    history.to_metadata(database.metadata)
    tasks.to_metadata(database.metadata)
    await app.core.db.startup(database)

    missing_templates = []

    # Data initialisation
    for table in [tasks, history]:
        backend = "nomad"
        match table.name:
            case "tasks":
                for job_type in ["batch", "sysbatch"]:
                    query = tasks.select().where(
                        tasks.c.name == f"generic-nomad-{job_type}",
                    )
                    if not await database.fetch_all(query):
                        tasks_app.log.debug(
                            "Generating %s template",
                            f"generic-nomad-{job_type}",
                        )
                        match job_type:
                            case "batch":
                                tpl = GENERIC_NOMAD_BATCH_TEMPLATE
                            case "sysbatch":
                                tpl = GENERIC_NOMAD_SYSBATCH_TEMPLATE
                            case _:
                                continue

                        task = Task(
                            name=tpl["Name"],
                            data=json.dumps(tpl),
                            backend=TASK_BACKEND_MAP[backend],
                            meta={"owners": ["*"]},
                        )
                        missing_templates.append(
                            tasks.insert().values(**task.model_dump()),
                        )
            case _:
                continue

    for missing_template in missing_templates:
        await database.execute(missing_template)


async def database_shutdown():
    """Perform a clean shutdown"""
    await database.disconnect()


@event.listens_for(Engine, "connect")
def prepare_connection(connection, record):
    """Prepare the connection"""
    app.core.db.prepare_connection(connection, record)


if __name__ == "__main__":
    # TODO: Rich formatting and custom logging handlers
    logging.basicConfig(
        level=settings.LOGGING,
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> "
        "%(module)s.%(funcName)s - %(message)s",
    )

    @tasks_app.on_event("startup")
    async def startup():
        await prepare_database()

    @tasks_app.on_event("shutdown")
    async def shutdown():
        await database_shutdown()

    import uvicorn

    uvicorn.run(
        tasks_app,
        host=tasks_settings.TASKS_ENDPOINT.host,
        port=tasks_settings.TASKS_ENDPOINT.port,
        ssl_keyfile=tasks_settings.TASKS_SSL_KEYFILE,
        ssl_certfile=tasks_settings.TASKS_SSL_CERTFILE,
    )
