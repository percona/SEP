"""
Tasks API
"""
from datetime import (
    datetime,
    timezone,
)
from http import HTTPStatus
import logging
from os import getenv
from secrets import token_hex
from typing import Annotated

from fastapi import (
    FastAPI,
    Form,
    HTTPException,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
)
from sqlalchemy import (
    event,
    null,
)
from sqlalchemy.engine import Engine
from starlette.middleware.sessions import SessionMiddleware

from .models import (
    history,
    Task,
    TaskBaseModel,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryBaseModel,
    TaskHistoryDataType,
    TASK_HISTORY_STATUS_MAP,
    tasks,
)
from sep.authz.casdoor import SESSION_TOKEN_LENGTH
import sep.core.db
from sep.core.utils import get_logger

DEFAULT_DATABASE_DSN = f"{sep.core.db.DEFAULT_DATABASE_DSN}/tasks.db"
DEFAULT_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000"

DATABASE_URL = getenv("REPORTS_DATABASE_URL", DEFAULT_DATABASE_DSN)
ORIGINS = getenv("REPORTS_ORIGINS", DEFAULT_ORIGINS).split(",")

database = sep.core.db.get_database(DATABASE_URL)
database.metadata = sep.core.db.get_metadata()
database.engine = sep.core.db.get_engine(DATABASE_URL, connect_args=sep.core.db.DEFAULT_DATABASE_CONNECT_ARGS)

app = FastAPI()
app.log = get_logger("tasks-api", level=logging.DEBUG)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=token_hex(SESSION_TOKEN_LENGTH),
    session_cookie="fastapi-session",
)


@app.on_event("startup")
async def startup():
    """Prepare the database and application"""
    history.to_metadata(database.metadata)
    tasks.to_metadata(database.metadata)
    await sep.core.db.startup(database)


@app.on_event("shutdown")
async def shutdown():
    """Perform a clean shutdown"""
    await database.disconnect()


@event.listens_for(Engine, "connect")
def prepare_connection(connection, record):
    """Prepare the connection"""
    sep.core.db.prepare_connection(connection, record)


@app.get(path="/", response_model=list[Task])
async def list_tasks():
    """List all tasks

    :return:
    """
    app.log.debug("Listing reports")
    query = tasks.select().where(tasks.c.deleted_at == null())
    return await database.fetch_all(query)


@app.delete(path="/{task}", response_class=JSONResponse)
async def delete_task(task: str):
    """Deleta a task

    :param task:
    :raises HTTPException: when the task does not exist
    :return: status message
    """
    app.log.debug("Deleting task %s", task)
    query = tasks.select().where(tasks.c.name == task, tasks.c.deleted_at == null())
    current_task = await database.fetch_one(query)
    if current_task is None:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)
    deleted_at = datetime.now(tz=timezone.utc)
    affected_rows = await database.execute(
        tasks.update().where(tasks.c.id == current_task[0]).values(deleted_at=deleted_at)
    )
    if affected_rows != 1:
        return {"error": f"failed to delete task {current_task[0]}"}
    return {"id": current_task[0], "deleted": True}


@app.get(path="/{task}", response_model=Task)
async def get_task(task: str):
    """Retrieve a task

    :param task:
    :return:
    """
    app.log.debug("Requesting task %s", task)
    query = tasks.select().where(tasks.c.name == task)
    return await database.fetch_one(query)


@app.get(path="/history/{task}", response_model=list[TaskHistory])
async def get_task_history(task: str):
    """Retrieve a task

    :param task:
    :return:
    """
    app.log.debug("Requesting task history for %s", task)
    query = history.select().where(history.c.name == task)
    return await database.fetch_all(query)


@app.post(path="/", response_model=Task)
async def create_task(task: TaskBaseModel):
    """Create a new task

    :param task:
    :return:
    """
    app.log.debug("Creating task %s", task.name)
    query = tasks.insert().values(**vars(task))
    last_record_id = await database.execute(query)
    return {**task.model_dump(), "id": last_record_id}


@app.post(path="/history", response_model=TaskHistory)
async def create_task_history(task: TaskHistoryBaseModel):
    """Create a new task

    :param task:
    :return:
    """
    app.log.debug("Creating task %s", task.name)
    query = history.insert().values(**vars(task))
    last_record_id = await database.execute(query)
    return {**task.model_dump(), "id": last_record_id}


@app.post(path="/execute/{task_name}", response_class=JSONResponse)
async def execute_task(task: Annotated[str, Form()], host: Annotated[str, Form()], task_name: str, request: Request):
    """Send a task for execution

    :param task:
    :param host:
    :param task_name:
    :param request:
    :return:
    """
    app.log.debug("Executing task %s", task_name)
    query = tasks.select().where(tasks.c.name == task_name)
    config = await database.fetch_one(query)
    if config is None:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)
    execution_request = TaskExecutionRequest(task=task, host=host)
    task = Task(**dict(config))
    task_history = TaskHistoryBaseModel(
        data=TaskHistoryDataType(task.model_dump_json()).__str__(),
        execution_request=execution_request.model_dump(),
        name=task.name,
        status=TASK_HISTORY_STATUS_MAP["pending"],
    )
    history_recorded = await database.execute(history.insert().values(**task_history.model_dump()))
    if not history_recorded:
        database.force_rollback()
        raise HTTPException(status_code=HTTPStatus.FAILED_DEPENDENCY)
    if "referer" in request.headers:
        return RedirectResponse(url=request.headers.get("referer"), status_code=HTTPStatus.SEE_OTHER)
    return {"task_history_id": history_recorded}
