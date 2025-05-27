"""Define routes for the Tasks API."""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy_celery_beat import PeriodicTask

from app.api.deps import IsAuthenticatedDep
from app.core.celery.deps import CeleryBeatSessionDep
from app.core.exceptions import HTTPBadRequestException, HTTPConflictException
from app.core.utils import utc_now
from app.tasks.celery import (
    dispatch_queue_item,
    execute_task_queue,
    get_executor_for_task,
)
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.deps import (
    ExecutableTaskDep,
    PreparedTaskHistory,
    SessionDep,
    TaskDep,
    TaskExecutor,
    TaskHistoryDep,
    TaskHistoryWithTaskDep,
)
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
    TaskLogType,
    TaskResponse,
    TaskStats,
    TaskWrite,
    TransformPayloadRequest,
)
from app.tasks.periodic.crud import PeriodicTaskManager
from app.tasks.periodic.models import PeriodicTaskCreate, PeriodicTaskResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


# TODO: Pagination  # noqa: TD002, TD003
@router.get("/", dependencies=[IsAuthenticatedDep], response_model=list[TaskResponse])
async def list_tasks(session: SessionDep, owner: str | None = None) -> list[Task]:
    """List all active tasks."""
    logger.debug("Listing tasks")
    return await TaskManager.list_active(session=session, owner=owner)


@router.delete(
    "/{task_name}",
    dependencies=[IsAuthenticatedDep],
    response_model=TaskResponse,
)
async def delete_task(
    session: SessionDep, celery_beat_session: CeleryBeatSessionDep, task_name: str
) -> Task:
    """Delete a task."""
    logger.debug("Deleting task %s", task_name)
    # TODO(yan): Delete for real
    # SEP-170
    task = await TaskManager.delete_by_name(session=session, name=task_name)
    await PeriodicTaskManager.delete_where(
        celery_beat_session,
        PeriodicTaskManager.build_where_clause_by_task_names(task_name),
    )
    return task


@router.get(
    "/{task_name}", dependencies=[IsAuthenticatedDep], response_model=TaskResponse
)
async def get_task(task: TaskDep) -> Task:
    """Retrieve a task by its name."""
    return task


@router.post(
    "/",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
async def create_task(session: SessionDep, task: TaskWrite) -> Task:
    """Create a new task."""
    logger.debug("Creating task %s", task.name)
    return await TaskManager.create(session, task)


@router.get(
    "/{task_name}/periodic/",
    dependencies=[IsAuthenticatedDep],
    response_model=list[PeriodicTaskResponse],
)
async def list_periodic_tasks_by_task_name(
    celery_beat_session: CeleryBeatSessionDep, task: ExecutableTaskDep
) -> list[PeriodicTask]:
    """List periodic tasks by task name."""
    return await PeriodicTaskManager.list_by_task_names(celery_beat_session, task.name)


@router.post(
    "/{task_name}/periodic/",
    dependencies=[IsAuthenticatedDep],
    response_model=PeriodicTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_periodic_task_for_task_name(
    celery_beat_session: CeleryBeatSessionDep,
    task: ExecutableTaskDep,
    periodic_task: PeriodicTaskCreate,
) -> PeriodicTask:
    """Create a new periodic task for the specified task name."""
    logger.debug("Creating periodic task %s", periodic_task)
    kwargs = json.loads(periodic_task.kwargs)
    kwargs["task_name"] = task.name
    if not periodic_task.name:
        periodic_task.name = f"run_{task.name}_{periodic_task.period}_{hash(periodic_task.kwargs)}".replace(
            " ", "_"
        )
    return await PeriodicTaskManager.create(
        celery_beat_session, periodic_task, kwargs=json.dumps(kwargs)
    )


@router.post(
    "/generate/", dependencies=[IsAuthenticatedDep], status_code=status.HTTP_201_CREATED
)
async def generate_task(
    session: SessionDep,
    generated_task: GeneratedTask,
    executor: TaskExecutor,
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
                name=f"step{i + 1}" if not cmd.get("name") else cmd["name"],
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

    return TaskHistory(
        task_id=task.id,
        execution_request=TaskExecutionRequest(
            task=generated_task.name,
            target=generated_task.target,
            meta={},
            tracking={"evaluation_id": ""},
        ),
        status=TaskHistoryStatusEnum.PENDING,
    )


@router.post(
    "/execute/{task_name}",
    dependencies=[IsAuthenticatedDep],
    response_model=TaskHistoryResponse,
)
async def execute_task_name(
    session: SessionDep,
    queue_item: PreparedTaskHistory,
    task_name: str,
) -> TaskHistory:
    """Send a task for execution."""
    logger.debug(
        "Dispatching task %s at %s",
        task_name,
        queue_item.execution_request.eta or utc_now(),
    )
    root_task = await TaskManager.get_root_task(session, queue_item.task)
    executor = get_executor_for_task(root_task)
    if queue_item.execution_request.target not in executor.get_hosts().values():
        raise HTTPBadRequestException(
            f"Failed to dispatch task: Target {queue_item.execution_request.target!r}"
            f"is not available in {executor.__class__.__name__} for task {task_name!r}"
        )
    if queue_item.execution_request.eta:
        history_recorded = await TaskHistoryManager.save(session, queue_item)
        celery_task = execute_task_queue.apply_async(
            args=[history_recorded.id], eta=history_recorded.execution_request.eta
        )
        history_recorded.execution_request.tracking["celery_task_id"] = celery_task.id
        return await TaskHistoryManager.save(
            session, history_recorded, flag_modified_fields=["execution_request"]
        )
    return await dispatch_queue_item(queue_item, session)


@router.get("/history/", dependencies=[IsAuthenticatedDep])
async def list_task_history(
    session: SessionDep,
    task_status: Annotated[TaskHistoryStatusEnum | None, Query(alias="status")] = None,
) -> list[TaskHistoryResponse]:
    """Create a new task."""
    logger.debug("Listing task history")
    return await TaskHistoryManager.list(
        session, select_related=(TaskHistory.task,), status=task_status
    )


@router.get(
    "/{task}/history/",
    dependencies=[IsAuthenticatedDep],
    response_model=list[TaskHistoryResponse],
)
async def get_task_history(
    session: SessionDep,
    task: str,
    task_status: Annotated[TaskHistoryStatusEnum | None, Query(alias="status")] = None,
) -> list[TaskHistory]:
    """Retrieve a task history by task name."""
    logger.debug("Requesting task history for %s", task)
    return await TaskHistoryManager.list_by_task_name(
        session=session,
        task_name=task,
        status=task_status,
        select_related_task=True,
    )


@router.get("/history/{task_history_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_task_history(
    task_history: TaskHistoryWithTaskDep,
) -> TaskHistoryResponse:
    """Retrieve a task history by id."""
    logger.debug("Requesting task history %s", task_history.id)
    return task_history


@router.get("/history/{task_history_id}/logs/", dependencies=[IsAuthenticatedDep])
async def stream_task_history_logs(
    executor: TaskExecutor, task_history: TaskHistoryDep
) -> StreamingResponse:
    """Stream a task history's logs."""
    logger.debug("Requesting logs for task history %s", task_history.id)
    if task_history.status == TaskHistoryStatusEnum.PENDING:
        raise HTTPConflictException("Task history is pending.")
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
            for log_type in TaskLogType
        )
    return StreamingResponse(
        stream_logs_generator,
        media_type="application/json",
    )


@router.post("/history/{task_history_id}/stop/", dependencies=[IsAuthenticatedDep])
async def stop_task_history(
    session: SessionDep, executor: TaskExecutor, task_history: TaskHistoryWithTaskDep
) -> TaskHistoryResponse:
    """Stop a task history."""
    logger.debug("Stopping task history %s", task_history.id)
    if task_history.status != TaskHistoryStatusEnum.RUNNING:
        raise HTTPBadRequestException(
            f"Cannot stop task history {task_history.id} ({task_history.task.name}): "
            f"task is not running (current status: {task_history.status})."
        )
    return await executor.stop_task(session, task_history)


@router.post(
    "/history/", dependencies=[IsAuthenticatedDep], status_code=status.HTTP_201_CREATED
)
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
