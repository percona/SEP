# Copyright (C) 2025 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

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

NOMAD_RUN_COMMAND = {
    "ID": "run-command",
    "Name": "run-command",
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
        "Payload": "forbidden",
        "MetaRequired": ["target", "command"],
        "MetaOptional": ["args"],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "ReschedulePolicy": {"Attempts": 0},
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
    Task(name="run-command", data=NOMAD_RUN_COMMAND, protected=True),
    Task(name="run-python", data=NOMAD_RUN_PYTHON, is_template=False, protected=True),
]

PERIODIC_TASKS = {
    IntervalSchedule(every=30, period=Period.SECONDS): [
        (
            "app.tasks.celery.sync_running_tasks",
            "sync_running_tasks",
            {"expire_seconds": 30},
        ),
    ],
}


async def init_tasks_db() -> None:
    """Initialize the database with generic Nomad task templates."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        system_tasks_names = []
        for task in SYSTEM_TASKS:
            system_tasks_names.append(task.name)
            task.created_by = None
            task.last_updated_by = None
            created_task, created = await TaskManager.get_or_create(
                session, task, {"name"}
            )
            if created:
                logger.info("Created system task %s", created_task.name)
            elif created_task.data != task.data:
                await TaskManager.update(
                    session,
                    created_task,
                    task,
                    flag_modified_fields=["data"],
                    last_updated_by=None,
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
    system_task_names = [
        "celery.backend_cleanup",
        "app.tasks.celery.execute_task_by_name",
    ]
    async with celery_beat_async_session() as celery_beat_session:
        for schedule, tasks in PERIODIC_TASKS.items():
            created_schedule, _ = await IntervalScheduleManager.get_or_create(
                celery_beat_session, schedule
            )
            for task_name, periodic_task_name, extra_kwargs in tasks:
                system_task_names.append(task_name)
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
        await BasePeriodicTaskManager.delete_where(
            celery_beat_session, PeriodicTask.task.not_in(system_task_names)
        )
        await celery_beat_session.commit()
