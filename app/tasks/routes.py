"""Define routes for the Tasks API."""

import logging
from http import HTTPStatus
from os import getenv
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import IsAuthenticatedDep
from app.core.exceptions import HTTPBadRequestException
from app.tasks.celery import trigger_task
from app.tasks.config import tasks_settings
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.deps import SessionDep, TaskExecutor, TaskHistoryDep
from app.tasks.models import (
    GeneratedTask,
    Task,
    TaskBackendEnum,
    TaskExecutionRequest,
    TaskGroup,
    TaskGroupTask,
    TaskGroupTaskTemplate,
    TaskHistory,
    TaskHistoryResponse,
    TaskHistoryStatusEnum,
    TaskLog,
    TaskStats,
    TransformPayloadRequest,
    TriggerRequest,
)
from app.tasks.utils import process_queue_item

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
        templates = [
            TaskGroupTaskTemplate(**config) for config in cmd.get("config", [])
        ]
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
    task_name: str,
    background_tasks: BackgroundTasks,
    history_recorded: TaskHistoryDep,
) -> dict[str, TaskHistory]:
    """Send a task for execution."""
    logger.debug("Executing task %s", task_name)
    if not history_recorded:
        raise HTTPException(status_code=HTTPStatus.FAILED_DEPENDENCY)
    return await _schedule_queue_item(history_recorded, background_tasks)


@router.post(
    "/trigger/{task_name}",
    dependencies=[IsAuthenticatedDep],
    response_class=JSONResponse,
)
async def trigger_task_name(
    task_name: str,
    trigger_data: TriggerRequest,
    history_recorded: TaskHistoryDep = None,
) -> JSONResponse:
    """Send a task for execution."""
    logger.debug("Executing task %s", task_name)
    if not history_recorded:
        raise HTTPException(status_code=HTTPStatus.FAILED_DEPENDENCY)
    task = trigger_task.apply_async(
        args=[history_recorded.id], countdown=trigger_data.countdown
    )
    return JSONResponse({"task_id": task.id})


@router.get("/history/", dependencies=[IsAuthenticatedDep])
async def list_task_history(
    session: SessionDep,
    status: TaskHistoryStatusEnum | None = None,
) -> list[TaskHistoryResponse]:
    """Create a new task."""
    logger.debug("Listing task history")
    return await TaskHistoryManager.list(
        session, select_related=(TaskHistory.task,), status=status
    )


@router.get(
    "/{task}/history/",
    dependencies=[IsAuthenticatedDep],
    response_model=list[TaskHistoryResponse],
)
async def get_task_history(
    session: SessionDep, task: str, status: TaskHistoryStatusEnum | None = None
) -> list[TaskHistory]:
    """Retrieve a task history by task name."""
    logger.debug("Requesting task history for %s", task)
    return await TaskHistoryManager.list_by_task_name(
        session=session,
        task_name=task,
        status=status,
        select_related_task=True,
    )


@router.get("/history/{task_history_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_task_history(
    session: SessionDep,
    task_history_id: int,
) -> TaskHistoryResponse:
    """Retrieve a task history by id."""
    logger.debug("Requesting task history %s", task_history_id)
    return await TaskHistoryManager.get_or_404(
        session=session,
        select_related=(TaskHistory.task,),
        id=task_history_id,
    )


@router.get("/history/{task_history_id}/logs/", dependencies=[IsAuthenticatedDep])
async def stream_task_history_logs(
    session: SessionDep, executor: TaskExecutor, task_history_id: int
) -> StreamingResponse:
    """Stream a task history's logs."""
    logger.debug("Requesting logs for task history %s", task_history_id)
    task_history = await TaskHistoryManager.get_or_404(
        session=session,
        id=task_history_id,
    )
    if task_history.status == TaskHistoryStatusEnum.PENDING:
        raise HTTPBadRequestException("Task history is pending.")
    if task_history.status == TaskHistoryStatusEnum.RUNNING:
        stream_logs_generator = (
            f"{log_line.model_dump_json()}\n" if log_line else ""
            async for log_line in executor.stream_logs(task_history)
        )
    else:
        stream_logs_generator = (
            f"{TaskLog(step=step, type=log_type, msg=log[log_type]).model_dump_json()}\n"
            for step, log in task_history.execution_request.tracking.get(
                "task_logs", {}
            ).items()
            for log_type in ("stdout", "stderr")
        )
    return StreamingResponse(
        stream_logs_generator,
        media_type="application/json",
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
                process_queue_item,
                queue_id=history_recorded.id,
            )
        case _:
            logger.critical("Unknown execution mode '%s'", mode)
            raise HTTPException(status_code=HTTPStatus.EXPECTATION_FAILED)
    return {"task_history_id": history_recorded}
