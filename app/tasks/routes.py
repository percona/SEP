"""Define routes for the Tasks API."""

import logging
from http import HTTPStatus
from os import getenv
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse

from app.api.deps import IsAuthenticatedDep
from app.core.auth.exceptions import HTTPForbiddenException
from app.tasks.config import tasks_settings
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.deps import get_executor, SessionDep, TaskExecutor
from app.tasks.models import (
    GeneratedTask,
    Task,
    TaskBackendEnum,
    TaskExecuteRequest,
    TaskExecutionRequest,
    TaskGroup,
    TaskGroupTask,
    TaskGroupTaskTemplate,
    TaskHistory,
    TaskHistoryResponse,
    TaskHistoryStatusEnum,
    TaskStats,
    TransformPayloadRequest,
)

logger = logging.getLogger(__name__)

DEFAULT_BACKEND_POLL_INTERVAL_SECONDS = 5
# TODO: Make all these getenv proper settings  # noqa: TD002, TD003
BACKEND_POLL_INTERVAL_SECONDS = getenv(
    "TASKS_BACKEND_POLL_INTERVAL_SECONDS",
    DEFAULT_BACKEND_POLL_INTERVAL_SECONDS,
)

router = APIRouter()


# TODO: Pagination  # noqa: TD002, TD003
@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_tasks(session: SessionDep, owner: str | None = None) -> list[Task]:
    """List all active tasks."""
    logger.debug("Listing tasks")
    return await TaskManager.list_active(session=session, owner=owner)


@router.delete(
    "/{task}",
    dependencies=[IsAuthenticatedDep],
    response_class=JSONResponse,
)
async def delete_task(session: SessionDep, task: str) -> dict[str, int | bool]:
    """Delete a task."""
    logger.debug("Deleting task %s", task)
    deleted_task = await TaskManager.delete_by_name(session=session, name=task)
    # TODO: Use Pydantic models  # noqa: TD002, TD003
    # TODO: Return deleted model  # noqa: TD002, TD003
    return {"id": deleted_task.id, "deleted": True}


@router.get("/{task}", dependencies=[IsAuthenticatedDep])
async def get_task(session: SessionDep, task: str) -> Task:
    """Retrieve a task by its name."""
    logger.debug("Requesting task %s", task)
    result = await TaskManager.retrieve_by_name(session=session, name=task)
    if not result:
        raise HTTPException(404, "Task not found")
    return result


@router.post("/", dependencies=[IsAuthenticatedDep])
async def create_task(session: SessionDep, task: Task) -> Task:
    """Create a new task."""
    logger.debug("Creating task %s", task.name)
    return await TaskManager.save(session, task)


@router.post("/generate/", dependencies=[IsAuthenticatedDep])
async def generate_task(
    session: SessionDep,
    generated_task: GeneratedTask,
    executor: TaskExecutor,
    background_tasks: BackgroundTasks,
) -> TaskHistory:
    """Generate a new task execution using a template."""
    logger.debug(
        "Generating task %s from %s",
        generated_task.name,
        generated_task.template,
    )
    template = await TaskManager.retrieve_by_name(
        session=session,
        name=f"generic-nomad-{generated_task.template}",
        is_template=True,
    )

    # TODO: enhance options for generating tasks  # noqa: TD002, TD003
    task = Task(
        name=generated_task.name,
        owner=generated_task.app,
        backend=template.backend,
        data=template.data,
    )
    tpl = task.data

    # TODO: currently Nomad-only, with restricted customisation  # noqa: TD002, TD003
    tg = TaskGroup(
        engine=task.backend.name,
        name="execution",
        tasks=[],
        parallel=generated_task.parallel and len(generated_task.commands) > 1,
    )
    for i, cmd in enumerate(generated_task.commands):
        templates = [TaskGroupTaskTemplate(**config) for config in cmd.get("config", [])]
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

    # TODO: delete Periodic for now  # noqa: TD002, TD003
    if "Periodic" in tpl:
        if generated_task.schedule and not generated_task.schedule.get("save_only"):
            tpl["Periodic"] = generated_task.schedule
        else:
            del tpl["Periodic"]

    match task.backend:
        case TaskBackendEnum.NOMAD:
            match tpl["Type"]:
                case "batch":
                    # TODO: handle more than one constraint  # noqa: TD002, TD003
                    if generated_task.target in ["all", "*"]:
                        tpl["Constraints"][0]["RTarget"] = ".*"
                        tpl["Constraints"][0]["Operand"] = "regexp"
                    else:
                        tpl["Constraints"][0]["RTarget"] = generated_task.target
                        tpl["Constraints"][0]["Operand"] = "="
            task.data = await executor.validate_job(tpl)
        case _:
            raise NotImplementedError(
                f"{task.backend} is currently unsupported",
            )

    if generated_task.persist:
        task = await TaskManager.save(session, task)

    task_history = TaskHistory(
        task_id=task.id,
        execution_request=TaskExecutionRequest(
            task=generated_task.name,
            target=generated_task.target,
            meta={},
            tracking={"evaluation_id": ""},
        ),
        status=TaskHistoryStatusEnum.PENDING,
    )

    if generated_task.schedule.get("save_only"):
        return task_history

    history_record = await TaskHistoryManager.save(session, task_history)
    # TODO: currently we trigger execution immediately as this is equivalent to /execute  # noqa: TD002, TD003
    #       Scheduling will require a periodic job for Nomad if using directly, else the
    #       ability to schedule generically from with the app
    if not generated_task.schedule:
        await _schedule_queue_item(
            history_recorded=history_record,
            background_tasks=background_tasks,
        )
    return history_record


@router.post(
    "/execute/{task_name}",
    dependencies=[IsAuthenticatedDep],
    response_class=JSONResponse,
)
async def execute_task_name(
    session: SessionDep,
    task_name: str,
    background_tasks: BackgroundTasks,
    execution_data: TaskExecuteRequest = None,
) -> dict[str, TaskHistory]:
    """Send a task for execution."""
    # TODO: optional arg (if possible), else a structured one  # noqa: TD002, TD003
    #           so that tasks can be executed with arbitrary parameters
    execution_data = TaskExecuteRequest() if execution_data is None else execution_data
    logger.debug("Executing task %s", task_name)
    config = await TaskManager.retrieve_by_name(session=session, name=task_name)
    if config.is_template:
        raise HTTPForbiddenException(
            f"Task {task_name} is a template and cannot be executed",
        )
    # Record the task execution request
    task_history = TaskHistory(
        task_id=config.id,
        execution_request=TaskExecutionRequest(
            task=task_name,
            target=execution_data.meta.get("target", "all"),
            meta=execution_data.meta,
            payload=execution_data.payload,
            tracking={"evaluation_id": ""},
        ),
        status=TaskHistoryStatusEnum.PENDING,
    )
    history_recorded = await TaskHistoryManager.save(session, task_history)
    if not history_recorded:
        raise HTTPException(status_code=HTTPStatus.FAILED_DEPENDENCY)
    return await _schedule_queue_item(history_recorded, background_tasks)


@router.post(
    "/run/{history_id}",
    dependencies=[IsAuthenticatedDep],
    response_class=JSONResponse,
)
async def execute_history_id(
    session: SessionDep,
    history_id: int,
    background_tasks: BackgroundTasks,
) -> dict[str, TaskHistory]:
    """Trigger a history item for processing."""
    history_record = await TaskHistoryManager.get_or_404(
        session,
        id=history_id,
        status=TaskHistoryStatusEnum.PENDING,
    )
    return await _schedule_queue_item(
        history_recorded=history_record,
        background_tasks=background_tasks,
    )


@router.get("/history/", dependencies=[IsAuthenticatedDep])
async def list_task_history(
    session: SessionDep,
    status: str | None = None,
) -> list[TaskHistory]:
    """Create a new task."""
    logger.debug("Listing task history")
    try:
         history_status = (
            TaskHistoryStatusEnum[status.upper()] if status is not None else None
        )
    except KeyError:
        logger.debug(
            "Status not found in TaskHistoryStatusEnum: %s",
            status,
            exc_info=True,
        )
        history_status = None
    return await TaskHistoryManager.list(session, status=history_status)


@router.get(
    "/{task}/history/",
    dependencies=[IsAuthenticatedDep],
    response_model=list[TaskHistoryResponse],
)
async def get_task_history(session: SessionDep, task: str) -> list[TaskHistory]:
    """Retrieve a task history by task name."""
    logger.debug("Requesting task history for %s", task)
    return await TaskHistoryManager.list_by_task_name(
        session=session,
        task_name=task,
        select_related_task=True,
    )


@router.get("/history/{task_history_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_task_history(
    session: SessionDep,
    task_history_id: int,
) -> TaskHistory:
    """Retrieve a task history by id."""
    logger.debug("Requesting task history %s", task_history_id)
    return await TaskHistoryManager.get_or_404(
        session=session,
        id=task_history_id,
    )


@router.post("/history/", dependencies=[IsAuthenticatedDep])
async def create_task_history(session: SessionDep, task: TaskHistory) -> TaskHistory:
    """Create a new task history."""
    logger.debug("Creating task history %s", task.name)
    return await TaskHistoryManager.save(session, task)


@router.get("/stats/{task}", dependencies=[IsAuthenticatedDep])
async def get_task_stats(session: SessionDep, task: str) -> TaskStats:
    """Calculate the statistics for the task."""
    logger.debug("Requesting task stats for %s", task)
    return TaskStats(
        tasks=await TaskHistoryManager.list_by_task_name(
            session=session,
            task_name=task,
            select_related_task=True,
        ),
    )


@router.get("/hosts/", dependencies=[IsAuthenticatedDep])
async def get_executor_hosts(executor: TaskExecutor) -> dict[str, str]:
    """Return the executor hosts from the executor."""
    return executor.get_hosts()


@router.post("/transform/", dependencies=[IsAuthenticatedDep])
async def transform_payload(
    executor: TaskExecutor,
    data: TransformPayloadRequest,
) -> dict[str, Any]:
    """Transform a payload string into a dictionary."""
    return await executor.transform_payload(data.payload, data.fmt)


async def _schedule_queue_item(
    history_recorded: TaskHistory,
    background_tasks: BackgroundTasks,
) -> dict[str, TaskHistory]:
    """Schedule queue item to execution."""
    # Check how to proceed with execution
    mode = tasks_settings.EXECUTE_MODE
    match mode:
        case "background":
            background_tasks.add_task(
                _process_queue_item,
                queue_id=history_recorded.id,
            )
        case _:
            logger.critical("Unknown execution mode '%s'", mode)
            raise HTTPException(status_code=HTTPStatus.EXPECTATION_FAILED)
    return {"task_history_id": history_recorded}


async def _process_queue_item(queue_id: int) -> None:
    """Process an item from the history table."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        queue_item = await TaskHistoryManager.get_or_404(
            session,
            select_related=[TaskHistory.task],
            id=queue_id,
        )
        task = queue_item.task

        if queue_item.status != TaskHistoryStatusEnum.PENDING:
            raise HTTPException(status_code=HTTPStatus.EXPECTATION_FAILED)

        match task.backend:
            case TaskBackendEnum.NOMAD:
                executor = get_executor()
            case _:
                raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)

        await executor.run(session, queue_item)
