"""Define utilities for the tasks app."""

from sqlalchemy_celery_beat import PeriodicTask
from sqlalchemy_celery_beat.models import Period

from app.core.celery.crud import BasePeriodicTaskManager, IntervalScheduleManager
from app.core.celery.db import (
    get_async_session_maker as get_celery_beat_async_session_maker,
)
from app.tasks.crud import TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.models import Task
from app.tasks.periodic.models import IntervalSchedule

GENERIC_NOMAD_BATCH_TEMPLATE = {
    "ID": "generic-nomad-batch",
    "Name": "generic-nomad-batch",
    "Type": "batch",
    "Datacenters": ["*"],
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
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "PreventRescheduleOnLost": True,
            "ReschedulePolicy": {"Attempts": 0},
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
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
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
    "Datacenters": ["*"],
    "Periodic": None,
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "PreventRescheduleOnLost": True,
            "ReschedulePolicy": {"Attempts": 0},
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
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [],
                },
            ],
        },
    ],
}

NOMAD_RUN_PYTHON = {
    "ID": "run-python",
    "Name": "run-python",
    "Type": "batch",
    "Datacenters": ["*"],
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
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "PreventRescheduleOnLost": True,
            "ReschedulePolicy": {"Attempts": 0},
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
    Task(
        name="generic-nomad-batch",
        data=GENERIC_NOMAD_BATCH_TEMPLATE,
        is_template=True,
        protected=True,
    ),
    Task(
        name="generic-nomad-sysbatch",
        data=GENERIC_NOMAD_SYSBATCH_TEMPLATE,
        is_template=True,
        protected=True,
    ),
    Task(name="run-python", data=NOMAD_RUN_PYTHON, is_template=False, protected=True),
]

PERIODIC_TASKS = {
    IntervalSchedule(every=30, period=Period.SECONDS): [
        (
            "app.tasks.celery.sync_running_tasks",
            "sync_running_tasks",
            {},
        ),
    ],
}


async def init_tasks_db() -> None:
    """Initialize the database with generic Nomad task templates."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        for task in SYSTEM_TASKS:
            created_task, created = await TaskManager.get_or_create(
                session, task, {"name"}
            )
            if not created and created_task.data != task.data:
                await TaskManager.update(
                    session, created_task, task, flag_modified_fields=["data"]
                )


async def init_periodic_tasks_db() -> None:
    """Initialize the database with required periodic tasks."""
    celery_beat_async_session = get_celery_beat_async_session_maker()
    async with celery_beat_async_session() as celery_beat_session:
        for schedule, tasks in PERIODIC_TASKS.items():
            created_schedule, _ = await IntervalScheduleManager.get_or_create(
                celery_beat_session, schedule
            )
            for task_name, periodic_task_name, extra_kwargs in tasks:
                if (
                    periodic_task := (
                        await BasePeriodicTaskManager.first(
                            celery_beat_session, task=task_name
                        )
                    )
                ) is None:
                    periodic_task = PeriodicTask(
                        name=periodic_task_name,
                        task=task_name,
                        schedule_model=created_schedule,
                        **extra_kwargs,
                    )
                else:
                    periodic_task.schedule_model = created_schedule
                    periodic_task.name = periodic_task_name
                    for key, value in extra_kwargs.items():
                        setattr(periodic_task, key, value)
                celery_beat_session.add(periodic_task)
        await celery_beat_session.commit()
