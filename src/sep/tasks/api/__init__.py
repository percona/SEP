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
from typing import (
    Annotated,
    Optional,
)

from fastapi import (
    BackgroundTasks,
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
from tornado.options import options

from .models import (
    history,
    Task,
    TASK_BACKEND_LOOKUP,
    TaskExecutionRequest,
    TaskHistory,
    TASK_HISTORY_STATUS_MAP,
    tasks,
)
from ..nomad import Executor as NomadExecutor
from sep.authz.casdoor import SESSION_TOKEN_LENGTH
import sep.core.db
from sep.core.utils import (
    get_logger,
    get_requests_session,
)

DEFAULT_BACKEND_POLL_INTERVAL_SECONDS = 5
DEFAULT_DATABASE_DSN = f"{sep.core.db.DEFAULT_DATABASE_DSN}/tasks.db"
DEFAULT_EXECUTION_MODE = "background"
DEFAULT_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000"

BACKEND_POLL_INTERVAL_SECONDS = getenv("TASKS_BACKEND_POLL_INTERVAL_SECONDS", DEFAULT_BACKEND_POLL_INTERVAL_SECONDS)
DATABASE_URL = getenv("TASKS_DATABASE_URL", DEFAULT_DATABASE_DSN)
ORIGINS = getenv("TASKS_ORIGINS", DEFAULT_ORIGINS).split(",")

database = sep.core.db.get_database(DATABASE_URL, include_engine=True)

app = FastAPI()
app.log = get_logger("tasks-api", level=logging.DEBUG)
app.log.debug("dialect._json_serializer: %r", database.engine.dialect._json_serializer)

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
    app.log.debug("Listing tasks")
    query = tasks.select().where(tasks.c.deleted_at == null())
    return await database.fetch_all(query)


@app.get(path="/history", response_model=list[TaskHistory])
async def list_task_history(request: Request):
    """Create a new task

    :param task:
    :return:
    """
    app.log.debug("Listing task history")
    query = history.select().where(history.c.deleted_at == null())
    if request.query_params.get("status"):
        query = sep.core.db.get_filtered_query(
            {"status": request.query_params.get("status")}, query=query, table=history, mapping=TASK_HISTORY_STATUS_MAP
        )
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
async def create_task(task: Task):
    """Create a new task

    :param task:
    :return:
    """
    app.log.debug("Creating task %s", task.name)
    query = tasks.insert().values(**task.model_dump())
    last_record_id = await database.execute(query)
    return {**task.model_dump(), "id": last_record_id}


@app.post(path="/history", response_model=TaskHistory)
async def create_task_history(task: TaskHistory):
    """Create a new task

    :param task:
    :return:
    """
    app.log.debug("Creating task history %s", task.name)
    query = history.insert().values(**vars(task))
    last_record_id = await database.execute(query)
    return {**task.model_dump(), "id": last_record_id}


@app.post(path="/execute/{task_name}", response_class=JSONResponse)
async def execute_task(
    task: Annotated[str, Form()],
    task_name: str,
    request: Request,
    background_tasks: BackgroundTasks,
    target: Optional[Annotated[str, Form()]] = Form("all"),
):
    """Send a task for execution

    TODO: optional arg (if possible), else a structured one
          so that tasks can be executed with arbitrary parameters

    :param task:
    :param target:
    :param task_name:
    :param request:
    :param background_tasks:
    :return:
    """
    app.log.debug("Executing task %s", task_name)
    query = tasks.select().where(tasks.c.name == task_name)
    config = await database.fetch_one(query)
    if config is None:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)
    # Record the task execution request
    meta = {
        field.replace("meta_", ""): val
        for field, val in dict(await request.form()).items()
        if field.startswith("meta_")
    }
    task_history = TaskHistory(
        data=Task(**dict(config)),
        execution_request=TaskExecutionRequest(task=task, target=target, meta=meta, tracking={"evaluation_id": ""}),
        name=task,
        status=TASK_HISTORY_STATUS_MAP["pending"],
    )
    history_recorded = await create_task_history(task=task_history)
    if not history_recorded:
        database.force_rollback()
        raise HTTPException(status_code=HTTPStatus.FAILED_DEPENDENCY)
    # Check how to proceed with execution
    try:
        mode = options.sep.tasks.execute_mode
    except AttributeError:
        app.log.warning("Task execution mode is not configured, using %s", DEFAULT_EXECUTION_MODE)
        mode = DEFAULT_EXECUTION_MODE

    match mode:
        case "background":
            background_tasks.add_task(_process_queue_item, queue_id=history_recorded["id"], request=request)
        case _:
            app.log.critical("Unknown execution mode '%s'", mode)
            raise HTTPException(status_code=HTTPStatus.EXPECTATION_FAILED)
    # Redirect the user
    redirect = request.query_params.get("next")
    if redirect is None and "referer" in request.headers:
        redirect = request.headers.get("referer")
    if redirect:
        app.log.debug("Redirecting to %s", redirect)
        return RedirectResponse(url=redirect, status_code=HTTPStatus.SEE_OTHER)
    return {"task_history_id": history_recorded}


async def _process_queue_item(queue_id: int, request: Request):
    """Process an item from the history table

    :param queue_id:
    :param request:
    :return:
    """
    queue_item = await database.fetch_one(history.select().where(history.c.id == queue_id))
    if queue_item is None:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)
    queue_item = dict(queue_item)
    execution_request = TaskExecutionRequest(**queue_item["execution_request"])
    task = Task(**queue_item["data"])

    if queue_item["status"] != TASK_HISTORY_STATUS_MAP["pending"]:
        raise HTTPException(status_code=HTTPStatus.EXPECTATION_FAILED)

    match TASK_BACKEND_LOOKUP[task.backend]:
        case "nomad":
            backend_config = options.modules["nomad"]["backend"]
            backend_config["session"] = get_requests_session(request)

            executor = NomadExecutor(backend_config, database, execution_request, task)
        case _:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)
    await executor.run(queue_item, BACKEND_POLL_INTERVAL_SECONDS)
