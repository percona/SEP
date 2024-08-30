"""Tasks API"""

import json
import logging
from collections import namedtuple
from datetime import datetime
from datetime import timezone
from http import HTTPStatus
from os import getenv
from typing import Annotated
from typing import Optional

from fastapi import BackgroundTasks
from fastapi import FastAPI
from fastapi import Form
from fastapi import HTTPException
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import event
from sqlalchemy import null
from sqlalchemy.engine import Engine

import app.core.db
from app.api.deps import IsAuthenticatedDep
from app.core.utils import get_timestamp
from app.tasks.config import tasks_settings
from app.tasks.models import GeneratedTask
from app.tasks.models import history
from app.tasks.models import Task
from app.tasks.models import TASK_BACKEND_LOOKUP
from app.tasks.models import TASK_BACKEND_MAP
from app.tasks.models import TASK_HISTORY_STATUS_MAP
from app.tasks.models import TaskExecutionRequest
from app.tasks.models import TaskGroup
from app.tasks.models import TaskGroupTask
from app.tasks.models import TaskGroupTaskTemplate
from app.tasks.models import TaskHistory
from app.tasks.models import tasks
from app.tasks.models import TaskStats
from app.tasks.nomad import Executor as NomadExecutor
from app.tasks.nomad.utils import transform_payload as nomad_payload

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
tasks_app.log = logger

tasks_app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
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


@tasks_app.get(path="/", dependencies=[IsAuthenticatedDep], response_model=list[Task])
async def list_tasks(request: Request):
    """List all tasks

    :param request:
    :return:
    """
    tasks_app.log.debug("Listing tasks")
    query = tasks.select().where(tasks.c.deleted_at == null())
    if request.query_params.get("owner"):
        query = app.core.db.get_filtered_query(
            {"owner": request.query_params.get("owner")},
            query=query,
            table=tasks,
            mapping=TASK_HISTORY_STATUS_MAP,
        )
    return await database.fetch_all(query)


@tasks_app.get(
    path="/history",
    dependencies=[IsAuthenticatedDep],
    response_model=list[TaskHistory],
)
async def list_task_history(request: Request):
    """Create a new task

    :param request:
    :return:
    """
    tasks_app.log.debug("Listing task history")
    query = history.select().where(history.c.deleted_at == null())
    if request.query_params.get("status"):
        query = app.core.db.get_filtered_query(
            {"status": request.query_params.get("status")},
            query=query,
            table=history,
            mapping=TASK_HISTORY_STATUS_MAP,
        )
    return await database.fetch_all(query)


@tasks_app.delete(
    path="/{task}",
    dependencies=[IsAuthenticatedDep],
    response_class=JSONResponse,
)
async def delete_task(task: str):
    """Deleta a task

    :param task:
    :raises HTTPException: when the task does not exist
    :return: status message
    """
    tasks_app.log.debug("Deleting task %s", task)
    query = tasks.select().where(tasks.c.name == task, tasks.c.deleted_at == null())
    current_task = await database.fetch_one(query)
    if current_task is None:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)
    deleted_at = datetime.now(tz=timezone.utc)
    affected_rows = await database.execute(
        tasks.update()
        .where(tasks.c.id == current_task[0])
        .values(deleted_at=deleted_at),
    )
    if affected_rows != 1:
        return {"error": f"failed to delete task {current_task[0]}"}
    return {"id": current_task[0], "deleted": True}


@tasks_app.get(path="/{task}", dependencies=[IsAuthenticatedDep], response_model=Task)
async def get_task(task: str):
    """Retrieve a task

    :param task:
    :return:
    """
    tasks_app.log.debug("Requesting task %s", task)
    query = tasks.select().where(tasks.c.name == task and tasks.c.deleted_at == null())
    result = await database.fetch_one(query)
    if not result:
        raise HTTPException(404, "Task not found")
    return result


@tasks_app.get(
    path="/history/{task}",
    dependencies=[IsAuthenticatedDep],
    response_model=list[TaskHistory],
)
async def get_task_history(task: str):
    """Retrieve a task

    :param task:
    :return:
    """
    tasks_app.log.debug("Requesting task history for %s", task)
    query = history.select().where(history.c.name == task)
    return await database.fetch_all(query)


@tasks_app.get(
    path="/stats/{task}",
    dependencies=[IsAuthenticatedDep],
    response_model=TaskStats,
)
async def get_task_stats(task: str):
    """Calculate the statistics for the task

    :param task:
    :return:
    """
    tasks_app.log.debug("Requesting task stats for %s", task)
    return TaskStats(
        tasks=[TaskHistory(**dict(item)) for item in await get_task_history(task)],
    )


@tasks_app.post(path="/", dependencies=[IsAuthenticatedDep], response_model=Task)
async def create_task(task: Task):
    """Create a new task

    :param task:
    :return:
    """
    tasks_app.log.debug("Creating task %s", task.name)
    query = tasks.insert().values(**task.model_dump())
    last_record_id = await database.execute(query)
    return {**task.model_dump(), "id": last_record_id}


@tasks_app.post(
    path="/generate",
    dependencies=[IsAuthenticatedDep],
    response_model=TaskHistory,
)
async def generate_task(
    generated_task: GeneratedTask,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Generate a new task execution using a template

    :param generated_task:
    :param request:
    :param background_tasks:
    :return:
    """
    tasks_app.log.debug(
        "Generating task %s from %s",
        generated_task.name,
        generated_task.template,
    )
    try:
        task = Task(
            **dict(
                await database.fetch_one(
                    tasks.select().where(
                        tasks.c.name == f"generic-nomad-{generated_task.template}",
                    ),
                ),
            ),
        )
    except TypeError:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Missing template",
        )

    # TODO: enhance options for generating tasks
    task.name = generated_task.name
    task.meta.update(owners=[generated_task.app])
    tpl = json.loads(task.data)

    # TODO: currently Nomad-only, with restricted customisation
    tg = TaskGroup(
        engine=TASK_BACKEND_LOOKUP[task.backend],
        name="execution",
        tasks=[],
        parallel=generated_task.parallel and len(generated_task.commands) > 1,
    )
    for i, cmd in enumerate(generated_task.commands):
        templates = []
        configs = cmd.get("config", [])
        if configs:
            for config in configs:
                templates.append(TaskGroupTaskTemplate(**config))
        tg.tasks.append(
            TaskGroupTask(
                name=f"step{i+1}" if not cmd.get("name") else cmd["name"],
                config={
                    "args": cmd.get("args"),
                    "command": cmd.get("command"),
                },
                meta=cmd.get("meta", {}),
                templates=templates,
            ),
        )
    tpl.update(tg.to_payload())

    # TODO: delete Periodic for now
    if "Periodic" in tpl:
        if generated_task.schedule and not generated_task.schedule.get("save_only"):
            tpl["Periodic"] = generated_task.schedule
        else:
            del tpl["Periodic"]

    match TASK_BACKEND_LOOKUP[task.backend]:
        case "nomad":
            match tpl["Type"]:
                case "batch":
                    # TODO: handle more than one constraint
                    if generated_task.target in ["all", "*"]:
                        tpl["Constraints"][0]["RTarget"] = ".*"
                        tpl["Constraints"][0]["Operand"] = "regexp"
                    else:
                        tpl["Constraints"][0]["RTarget"] = generated_task.target
                        tpl["Constraints"][0]["Operand"] = "="
            task.data = await nomad_payload(
                payload=json.dumps(tpl),
                payload_format="json",
            )
        case _:
            raise NotImplementedError(
                f"{TASK_BACKEND_LOOKUP[task.backend]} is currently unsupported",
            )

    if generated_task.persist:
        task.id = None
        await create_task(task)

    task_history = TaskHistory(
        data=task,
        execution_request=TaskExecutionRequest(
            task=generated_task.name,
            target=generated_task.target,
            meta={},
            tracking={"evaluation_id": ""},
        ),
        name=task.name,
        status=TASK_HISTORY_STATUS_MAP["pending"],
    )

    if generated_task.schedule.get("save_only"):
        return task_history

    history_record = await create_task_history(task_history)
    # TODO: currently we trigger execution immediately as this is equivalent to /execute
    #       Scheduling will require a periodic job for Nomad if using directly, else the
    #       ability to schedule generically from with the app
    if not generated_task.schedule:
        await _schedule_queue_item(
            history_recorded=history_record,
            request=request,
            background_tasks=background_tasks,
        )
    return history_record


@tasks_app.post(
    path="/history",
    dependencies=[IsAuthenticatedDep],
    response_model=TaskHistory,
)
async def create_task_history(task: TaskHistory):
    """Create a new task

    :param task:
    :return:
    """
    tasks_app.log.debug("Creating task history %s", task.name)
    query = history.insert().values(**vars(task))
    last_record_id = await database.execute(query)
    return {**task.model_dump(), "id": last_record_id}


@tasks_app.post(
    path="/run/{history_id}",
    dependencies=[IsAuthenticatedDep],
    response_class=JSONResponse,
)
async def execute_history_id(
    history_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Trigger a history item for processing

    :param history_id:
    :param request:
    :param background_tasks:
    :return:
    """
    history_record = await database.fetch_one(
        history.select().where(history.c.id == history_id),
    )
    if not history_record:
        tasks_app.log.error("No match found for tasks.history.id = %d", history_id)
        return {}
    if history_record["status"] != TASK_HISTORY_STATUS_MAP["pending"]:
        tasks_app.log.error(
            "Item status for tasks.history.id = %d is %s",
            history_id,
            TASK_BACKEND_LOOKUP[history_record["status"]],
        )
        return {}
    record = await _schedule_queue_item(
        history_recorded=dict(history_record),
        request=request,
        background_tasks=background_tasks,
    )
    return record


@tasks_app.post(
    path="/execute/{task_name}",
    dependencies=[IsAuthenticatedDep],
    response_class=JSONResponse,
)
async def execute_task_name(
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
    tasks_app.log.debug("Executing task %s", task_name)
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
        execution_request=TaskExecutionRequest(
            task=task_name,
            target=target,
            meta=meta,
            tracking={"evaluation_id": ""},
        ),
        name=task_name,
        status=TASK_HISTORY_STATUS_MAP["pending"],
    )
    history_recorded = await create_task_history(task=task_history)
    if not history_recorded:
        database.force_rollback()
        raise HTTPException(status_code=HTTPStatus.FAILED_DEPENDENCY)
    return await _schedule_queue_item(history_recorded, background_tasks, request)


async def _schedule_queue_item(
    history_recorded: dict,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """:param history_recorded:
    :param background_tasks:
    :param request:
    :return:
    """
    # Check how to proceed with execution
    try:
        mode = tasks_settings.EXECUTE_MODE
    except AttributeError:
        tasks_app.log.warning(
            "Task execution mode is not configured, using %s",
            DEFAULT_EXECUTION_MODE,
        )
        mode = DEFAULT_EXECUTION_MODE

    match mode:
        case "background":
            background_tasks.add_task(
                _process_queue_item,
                queue_id=history_recorded["id"],
                request=request,
            )
        case _:
            tasks_app.log.critical("Unknown execution mode '%s'", mode)
            raise HTTPException(status_code=HTTPStatus.EXPECTATION_FAILED)
    # Redirect the user
    # redirect = request.query_params.get("next")
    # if redirect is None and "referer" in request.headers:
    #    redirect = request.headers.get("referer")
    # if redirect:
    #    app.log.debug("Redirecting to %s", redirect)
    #    return RedirectResponse(url=redirect, status_code=HTTPStatus.SEE_OTHER)
    return {"task_history_id": history_recorded}


async def _process_queue_item(queue_id: int, request: Request):
    """Process an item from the history table

    :param queue_id:
    :param request:
    :return:
    """
    queue_item = await database.fetch_one(
        history.select().where(history.c.id == queue_id),
    )
    if queue_item is None:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)
    queue_item = dict(queue_item)
    execution_request = TaskExecutionRequest(**queue_item["execution_request"])
    task = Task(**queue_item["data"])

    if queue_item["status"] != TASK_HISTORY_STATUS_MAP["pending"]:
        raise HTTPException(status_code=HTTPStatus.EXPECTATION_FAILED)

    match TASK_BACKEND_LOOKUP[task.backend]:
        case "nomad":
            backend_config = {
                "address": tasks_settings.NOMAD.ENDPOINT,
                "secure": tasks_settings.NOMAD.SECURE,
                "timeout": tasks_settings.NOMAD.TIMEOUT,
                "verify": tasks_settings.NOMAD.VERIFY,
            }
            executor = NomadExecutor(backend_config, database, execution_request, task)
        case _:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)

    processed_request, status = await executor.run(
        queue_item,
        BACKEND_POLL_INTERVAL_SECONDS,
    )
    async with database.engine.begin() as conn:
        await conn.execute(
            history.update()
            .where(history.c.id == queue_id)
            .values(
                status=status,
                updated_at=get_timestamp(),
                execution_request=processed_request,
            ),
        )
