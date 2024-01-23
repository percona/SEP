"""
Tasks API
"""
from asyncio import sleep
from datetime import (
    datetime,
    timezone,
)
from http import HTTPStatus
import json
import logging
from os import getenv
from secrets import token_hex
from typing import (
    Annotated,
    Optional,
)

import nomad
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
from ..nomad import Executor
from sep.authz.casdoor import SESSION_TOKEN_LENGTH
import sep.core.db
from sep.core.utils import (
    get_logger,
    get_requests_session,
    get_timestamp,
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
    # TODO: add check to ensure that only pending jobs are processed here
    execution_request = TaskExecutionRequest(**dict(queue_item)["execution_request"])
    task = Task(**dict(queue_item)["data"])

    match TASK_BACKEND_LOOKUP[task.backend]:
        case "nomad":
            backend_config = options.modules["nomad"]["backend"]
            backend_config["session"] = get_requests_session(request)

            executor = Executor().setup(backend_config, database, execution_request, task)
            await executor.run(dict(queue_item), BACKEND_POLL_INTERVAL_SECONDS)

            #backend = nomad.Nomad(**backend_config)

            ## TODO: determine scenarios for execution, such as looking up an existing job
            #task_data = json.loads(task.data)
            #if queue_item["execution_request"].get("meta"):
            #    # TODO: target is currently pushed in to meta
            #    queue_item["execution_request"]["meta"]["target"] = queue_item["execution_request"]["target"]
            #    # TODO: DC is currently forced
            #    queue_item["execution_request"]["meta"]["dc"] = "dc1"
            #    # TODO: allow templates in more fields, currently only for constraints
            #    for meta_var, meta_val in queue_item["execution_request"]["meta"].items():
            #        for i, constraint in enumerate(task_data["Constraints"]):
            #            meta = "${NOMAD_META_" + meta_var + "}"
            #            task_data["Constraints"][i] = json.loads(json.dumps(constraint).replace(meta, meta_val))

            ## TODO: check status
            ##
            ## Example response:
            ##       {"EvalID":"5d87d645-9e98-e9b2-f6e8-380256bb5cf5",
            ##       "EvalCreateIndex":8633,
            ##       "JobModifyIndex":8633,
            ##       "Warnings":"",
            ##       "Index":8633,
            ##       "LastContact":0,
            ##       "KnownLeader":false,
            ##       "NextToken":""}
            ##
            #try:
            #    job = backend.job.get_job(task.name)
            #    status = backend.job.evaluate_job(task.name)
            #except nomad.api.exceptions.BaseNomadException:
            #    status = backend.jobs.register_job({"Job": task_data})
            #    app.log.debug("Job status: %r", status)
            #    job = backend.job.get_job(task.name)

            #execution_request.tracking.update(evaluation_id=status["EvalID"])
            #async with database.engine.begin() as conn:
            #    await conn.execute(
            #        history.update().where(history.c.id == queue_id).values(execution_request=execution_request)
            #    )

            #allocation_filters = [f'JobID == "{job["ID"]}"', f'EvalID == "{status["EvalID"]}"']
            #allocations = backend.allocations.get_allocations(filter_=" && ".join(allocation_filters))
            #app.log.debug("Job: %r", job)
            #app.log.debug("Allocations: %r", [x["JobID"] for x in allocations])

            #if job["ParameterizedJob"]:
            #    # Example content:
            #    # "ParameterizedJob": {"MetaOptional": ["args", "image"], "MetaRequired": ["command"], "Payload": ""}
            #    # https://python-nomad.readthedocs.io/en/latest/api/job/#dispatch-job
            #    raise NotImplementedError("Parameterized job support is TBD")

            #async with database.engine.begin() as conn:
            #    await conn.execute(
            #        history.update()
            #        .where(history.c.id == queue_id)
            #        .values(status=TASK_HISTORY_STATUS_MAP["running"], updated_at=get_timestamp())
            #    )

            #alloc = allocations[0]
            #while True:
            #    match job["Type"]:
            #        case "batch":
            #            raise NotImplementedError("Batch job support is TBD")
            #        case "service":
            #            raise NotImplementedError("Service job support is TBD")
            #        case "system" | "sysbatch":
            #            alloc = backend.allocations.get_allocations(filter_=f'EvalID == "{alloc["EvalID"]}"')[0]
            #        case _:
            #            raise NotImplementedError(f'Unrecognized job type \'{job["Type"]}\'')
            #    if alloc["ClientStatus"] in ["completed", "failed"]:
            #        break
            #    await sleep(BACKEND_POLL_INTERVAL_SECONDS)
            ## Check status
            #status = 0
            #if alloc["ClientStatus"] == "failed":
            #    for state in alloc["TaskStates"].values():
            #        status += sum([x["ExitCode"] for x in state["Events"]])

            #execution_request.tracking.update(task_states=alloc["TaskStates"])
            #async with database.engine.begin() as conn:
            #    await conn.execute(
            #        history.update()
            #        .where(history.c.id == queue_id)
            #        .values(
            #            status=TASK_HISTORY_STATUS_MAP["failed" if status > 0 else "success"],
            #            updated_at=get_timestamp(),
            #            execution_request=execution_request,
            #        )
            #    )

        case _:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)
