"""Define utilities for the tasks app."""

import logging

from sqlalchemy_celery_beat import PeriodicTask
from sqlalchemy_celery_beat.models import Period
from sqlmodel import col

from app.core.celery.crud import BasePeriodicTaskManager, IntervalScheduleManager
from app.core.celery.db import (
    get_async_session_maker as get_celery_beat_async_session_maker,
)
from app.core.utils.date_time import utc_now
from app.tasks.crud import TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.models import Task
from app.tasks.periodic.models import IntervalSchedule

logger = logging.getLogger(__name__)

NOMAD_RUN_COMMAND = {
    "ID": "run-command",
    "Name": "run-command",
    "Type": "batch",
    "Datacenters": ["dc1"],
    "Constraints": [
        {
            "LTarget": "${node.unique.name}",
            "RTarget": "${NOMAD_META_target}",
            "Operand": "=",
        },
    ],
    "ParameterizedJob": {
        "Payload": "forbidden",
        "MetaRequired": ["target", "command"],
        "MetaOptional": ["args"],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "Tasks": [
                {
                    "Name": "run-script",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "xargs",
                        "args": [
                            "--arg-file",
                            "args_file",
                            "${NOMAD_META_command}",
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": '{{ env "NOMAD_META_args" }}',
                            "DestPath": "args_file",
                        },
                    ],
                },
            ],
        },
    ],
}

NOMAD_RUN_PYTHON = {
    "ID": "run-python",
    "Name": "run-python",
    "Type": "batch",
    "Datacenters": ["dc1"],
    "Constraints": [
        {
            "LTarget": "${node.unique.name}",
            "RTarget": "${NOMAD_META_target}",
            "Operand": "=",
        },
    ],
    "ParameterizedJob": {
        "Payload": "required",
        "MetaRequired": ["target"],
        "MetaOptional": ["config", "requirements"],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "Tasks": [
                {
                    "Name": "prepare-env",
                    "Lifecycle": {"hook": "prestart", "sidecar": False},
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            "python3 -m venv ${NOMAD_ALLOC_DIR}/venv;"
                            "${NOMAD_ALLOC_DIR}/venv/bin/pip install -r requirements.txt",
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": '{{ env "NOMAD_META_requirements" }}',
                            "DestPath": "requirements.txt",
                        },
                    ],
                },
                {
                    "Name": "run-script",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            "gzip -d ${NOMAD_TASK_DIR}/script.py.gz;"
                            "${NOMAD_ALLOC_DIR}/venv/bin/python3 -u ${NOMAD_TASK_DIR}/script.py --config script_config",
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": '{{ env "NOMAD_META_config" }}',
                            "DestPath": "script_config",
                        },
                    ],
                    "DispatchPayload": {"file": "script.py.gz"},
                },
                {
                    "Name": "clean-up",
                    "Lifecycle": {"hook": "poststop", "sidecar": False},
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "rm",
                        "args": [
                            "-rf",
                            "${NOMAD_ALLOC_DIR}/venv",
                            "requirements.txt",
                            "script_config",
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                },
            ],
        },
    ],
}

SYSTEM_TASKS = [
    Task(name="run-command", data=NOMAD_RUN_COMMAND, protected=True),
    Task(name="run-python", data=NOMAD_RUN_PYTHON, protected=True),
]


async def init_tasks_db() -> None:
    """Initialize the database with generic Nomad task templates."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        system_tasks_names = []
        for task in SYSTEM_TASKS:
            system_tasks_names.append(task.name)
            created_task, created = await TaskManager.get_or_create(
                session, task, {"name"}
            )
            if created:
                logger.info("Created system task %s", created_task.name)
            elif created_task.data != task.data:
                await TaskManager.update(
                    session, created_task, task, flag_modified_fields=["data"]
                )
                logger.info(
                    "Updated system task %s with new data: %s",
                    created_task.name,
                    task.data,
                )
        delete_result = await TaskManager.delete_unattached_system_tasks(
            session, system_tasks_names
        )
        if delete_result.rowcount:
            logger.info(
                "Deleted %s system tasks that are no longer needed.",
                delete_result.rowcount,
            )
        update_delete_result = await TaskManager.update_where(
            session,
            {"deleted_at": utc_now()},
            col(Task.name).not_in(system_tasks_names),
            col(Task.protected).is_(True),
        )
        if update_delete_result.rowcount:
            logger.info(
                "Marked %s unused system tasks with attached runs as deleted.",
                update_delete_result.rowcount,
            )


async def init_periodic_tasks_db() -> None:
    """Initialize the database with required periodic tasks."""
    celery_beat_async_session = get_celery_beat_async_session_maker()
    periodic_task_name = "process_expired_and_orphaned_periodic_tasks_every_30_seconds"
    async with celery_beat_async_session() as celery_beat_session:
        if (
            await BasePeriodicTaskManager.first(
                celery_beat_session, name=periodic_task_name
            )
            is None
        ):
            schedule, _ = await IntervalScheduleManager.get_or_create(
                celery_beat_session, IntervalSchedule(every=30, period=Period.SECONDS)
            )
            periodic_task = PeriodicTask(
                name=periodic_task_name,
                task="app.tasks.celery.process_expired_and_orphaned_periodic_tasks",
                schedule_model=schedule,
            )
            celery_beat_session.add(periodic_task)
            await celery_beat_session.commit()
