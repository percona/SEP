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

"""Define the database initial data for the Tasks app."""

import logging

from sqlalchemy_celery_beat.models import Period
from sqlmodel import col

from app.core.celery.models import IntervalSchedule
from app.core.celery.utils import (
    init_periodic_tasks_db,
    SystemPeriodicTaskData,
    SystemPeriodicTaskSchedule,
)
from app.core.utils.date_time import utc_now
from app.tasks.crud import TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.models import SYSTEM_USER, Task

logger = logging.getLogger(__name__)

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
        "MetaOptional": ["config", "config_nomad_variable", "requirements"],
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
                            "${NOMAD_ALLOC_DIR}/venv/bin/python3"
                            " -u ${NOMAD_TASK_DIR}/script.py --config ${NOMAD_TASK_DIR}/script_config",
                        ],
                        "work_dir": "${NOMAD_TASK_DIR}/output_files",
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": '{{- $var := env "NOMAD_META_config_nomad_variable" -}}{{- if $var -}}{{ with nomadVar $var }}{{ .config }}{{ end }}{{- else -}}{{ env "NOMAD_META_config" }}{{- end -}}',
                            "DestPath": "local/script_config",
                        },
                        {
                            "EmbeddedTmpl": ".keep",
                            "DestPath": "local/output_files/.keep",
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

NOMAD_EXEC_ARTIFACT = {
    "ID": "exec-artifact",
    "Name": "exec-artifact",
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
        "MetaRequired": [
            "target",
            "snippet_source",
            "interpreter",
            "access_token",
            "md5_checksum",
        ],
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
                            "${NOMAD_TASK_DIR}/args_file",
                            "env",
                            "-S",
                            "${NOMAD_META_interpreter}",
                            "${NOMAD_TASK_DIR}/script",
                        ],
                        "work_dir": "${NOMAD_TASK_DIR}/output_files",
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": '{{ env "NOMAD_META_args" }}',
                            "DestPath": "local/args_file",
                        },
                        {
                            "EmbeddedTmpl": ".keep",
                            "DestPath": "local/output_files/.keep",
                        },
                    ],
                    "Artifacts": [
                        {
                            "GetterSource": "${NOMAD_META_snippet_source}",
                            "GetterMode": "file",
                            "RelativeDest": "local/script",
                            "GetterHeaders": {
                                "Authorization": "Bearer ${NOMAD_META_access_token}"
                            },
                            "GetterOptions": {
                                "checksum": "md5:${NOMAD_META_md5_checksum}",
                            },
                            "GetterInsecure": True,
                        }
                    ],
                },
            ],
        },
    ],
}

SYSTEM_TASKS = [
    Task(
        name="run-command",
        data=NOMAD_RUN_COMMAND,
        protected=True,
        anonymize_mask=None,
        created_by=SYSTEM_USER,
    ),
    Task(
        name="run-python",
        data=NOMAD_RUN_PYTHON,
        protected=True,
        anonymize_mask=None,
        output_files_path="run-script/local/output_files",
        created_by=SYSTEM_USER,
    ),
    Task(
        name="exec-artifact",
        data=NOMAD_EXEC_ARTIFACT,
        protected=True,
        anonymize_mask=None,
        output_files_path="run-script/local/output_files",
        created_by=SYSTEM_USER,
    ),
]

# Import plugin tasks
try:
    from app.sep.plugins.mum.task import get_default_mum_task

    _mum_task = get_default_mum_task()
    SYSTEM_TASKS.append(
        Task(
            name=_mum_task.name,
            data=_mum_task.data,
            backend=_mum_task.backend,
            owner=_mum_task.owner,
            protected=_mum_task.protected,
            alert_on_fail=_mum_task.alert_on_fail,
            anonymize_mask=None,
            created_by=SYSTEM_USER,
        )
    )
except ImportError:
    # MUM plugin not available, skip
    pass

SYSTEM_PERIODIC_TASKS = [
    SystemPeriodicTaskSchedule(
        schedule=IntervalSchedule(every=30, period=Period.SECONDS),
        tasks=[
            SystemPeriodicTaskData(
                name="tasks__sync_running_tasks",
                task_name="app.tasks.celery.sync_running_tasks",
                extra_kwargs={"expire_seconds": 30},
            ),
        ],
    )
]


async def init_tasks_db() -> None:
    """Initialize the Tasks database with system tasks and periodic tasks."""
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
                    session,
                    created_task,
                    task,
                    flag_modified_fields=["data"],
                    last_updated_by=SYSTEM_USER,
                )
                logger.info(
                    "Updated system task %s with new data: %s",
                    created_task.name,
                    task.data,
                )
            elif created_task.model_dump(
                exclude={"id", "created_at", "updated_at", "deleted_at"}
            ) != task.model_dump(
                exclude={"id", "created_at", "updated_at", "deleted_at"}
            ):
                logger.debug("Created task: %s", created_task.model_dump())
                logger.debug("New task: %s", task.model_dump())
                await TaskManager.update(session, created_task, task)
                logger.info("Updated system task %s", created_task.name)
        await TaskManager.update_where(
            session,
            {"deleted_at": None},
            col(Task.name).in_(system_tasks_names),
            col(Task.deleted_at).is_not(None),
        )
        delete_result = await TaskManager.delete_unattached_system_tasks(
            session, exclude_task_names=system_tasks_names
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
            col(Task.deleted_at).is_(None),
        )
        if update_delete_result.rowcount:
            logger.info(
                "Marked %s unused system tasks with attached runs as deleted.",
                update_delete_result.rowcount,
            )
    await init_periodic_tasks_db(SYSTEM_PERIODIC_TASKS, "tasks__")
