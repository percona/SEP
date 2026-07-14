# Copyright (C) 2026 Percona LLC
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
from copy import deepcopy

from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy_celery_beat.models import Period
from sqlmodel import col

from app.core.celery.models import IntervalSchedule
from app.core.celery.utils import (
    init_periodic_tasks_db,
    SystemPeriodicTaskData,
    SystemPeriodicTaskSchedule,
)
from app.core.utils.date_time import utc_now
from app.core.utils.fields import DatabaseDialect
from app.tasks.config import tasks_settings
from app.tasks.crud import TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.db.engine import engine
from app.tasks.models import (
    CHECK_NOMAD_CERT_EXPIRY_TASK_NAME,
    INVENTORY_SYNC_TASK_NAME,
    SYNC_RUNNING_TASKS_TASK_NAME,
    SYSTEM_USER,
    Task,
    TaskBackendEnum,
)

logger = logging.getLogger(__name__)

# POSIX sh preamble that aborts a Nomad allocation when
# ``now - scheduled_at`` exceeds the configured staleness threshold. Missing
# or empty meta values short-circuit to a no-op for rollback safety.
#
# NOTE: shell variables are referenced with the bareword form (``$name``) and
# never the brace form (``${name}``). Nomad interpolates ``${...}`` in
# ``raw_exec`` args through its own variable table before spawning the shell,
# and fails config validation for references it does not know (e.g. the shell
# local ``${elapsed}``). The ``""s`` after each variable name disambiguates the
# variable name from the trailing literal ``s`` so ``$elapseds`` is not parsed
# as a single (unset) variable name.
STALENESS_PREAMBLE_SHELL = (
    'if [ -n "$NOMAD_META_scheduled_at" ] && '
    '[ -n "$NOMAD_META_staleness_threshold_seconds" ]; then '
    "now=$(date +%s); "
    "elapsed=$((now - NOMAD_META_scheduled_at)); "
    'if [ "$elapsed" -gt "$NOMAD_META_staleness_threshold_seconds" ]; then '
    'echo "SEP_STALE_SKIP: elapsed=$elapsed""s '
    'threshold=$NOMAD_META_staleness_threshold_seconds""s"; '
    "exit 75; "
    "fi; "
    "fi"
)

_CHECK_STALENESS_TASK = {
    "Name": "check-staleness",
    "Lifecycle": {"hook": "prestart", "sidecar": False},
    "Driver": "raw_exec",
    "User": "",
    "Config": {
        "command": "sh",
        "args": ["-c", STALENESS_PREAMBLE_SHELL],
    },
    "Meta": {},
    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
}

_STALENESS_META_OPTIONAL = ["scheduled_at", "staleness_threshold_seconds"]

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
        "MetaOptional": ["args", *_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "ReschedulePolicy": {"Attempts": 0},
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
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
        "MetaOptional": ["config", "requirements", *_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "PreventRescheduleOnLost": True,
            "ReschedulePolicy": {"Attempts": 0},
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
                {
                    "Name": "prepare-env",
                    "Lifecycle": {"hook": "prestart", "sidecar": False},
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            f"{STALENESS_PREAMBLE_SHELL}; "
                            "python3 -m venv --copies ${NOMAD_ALLOC_DIR}/venv;"
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
                            "EmbeddedTmpl": '{{ env "NOMAD_META_config" }}',
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
            "md5_checksum",
        ],
        "MetaOptional": ["args", *_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
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

NOMAD_EXEC_PYTHON_ARTIFACT = {
    "ID": "exec-python-artifact",
    "Name": "exec-python-artifact",
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
            "md5_checksum",
        ],
        "MetaOptional": ["args", "requirements", *_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "PreventRescheduleOnLost": True,
            "ReschedulePolicy": {"Attempts": 0},
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
                {
                    "Name": "prepare-env",
                    "Lifecycle": {"hook": "prestart", "sidecar": False},
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            f"{STALENESS_PREAMBLE_SHELL}; "
                            "python3 -m venv --copies ${NOMAD_ALLOC_DIR}/venv;"
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
                            "PYTHON_CMD=${NOMAD_ALLOC_DIR}/venv/bin/python3;"
                            'case "${NOMAD_META_interpreter}" in "sudo "*) '
                            'PYTHON_CMD="sudo ${NOMAD_ALLOC_DIR}/venv/bin/python3";; esac;'
                            "xargs --arg-file ${NOMAD_TASK_DIR}/args_file -- "
                            "$PYTHON_CMD -u ${NOMAD_TASK_DIR}/script",
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
                            "GetterOptions": {
                                "checksum": "md5:${NOMAD_META_md5_checksum}",
                            },
                            "GetterInsecure": True,
                        }
                    ],
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
    Task(
        name="exec-python-artifact",
        data=NOMAD_EXEC_PYTHON_ARTIFACT,
        protected=True,
        anonymize_mask=None,
        output_files_path="run-script/local/output_files",
        created_by=SYSTEM_USER,
    ),
    Task(
        name=INVENTORY_SYNC_TASK_NAME,
        data={
            "callable": "app.sep.apps.inventory.sync.run_scheduled_inventory_sync",
            "target": "local",
        },
        backend=TaskBackendEnum.CELERY,
        protected=True,
        created_by=SYSTEM_USER,
    ),
]

SYSTEM_PERIODIC_TASKS = [
    SystemPeriodicTaskSchedule(
        schedule=IntervalSchedule(every=30, period=Period.SECONDS),
        tasks=[
            SystemPeriodicTaskData(
                name=SYNC_RUNNING_TASKS_TASK_NAME,
                task_name="app.tasks.celery.sync_running_tasks",
                extra_kwargs={"expire_seconds": 30},
            ),
        ],
    )
]

_nomad_cert_schedule = tasks_settings.NOMAD.check_cert_expiry_interval
if _nomad_cert_schedule is not None:
    SYSTEM_PERIODIC_TASKS.append(
        SystemPeriodicTaskSchedule(
            schedule=_nomad_cert_schedule,
            tasks=[
                SystemPeriodicTaskData(
                    name=CHECK_NOMAD_CERT_EXPIRY_TASK_NAME,
                    task_name="app.tasks.celery.check_nomad_cert_expiry",
                ),
            ],
        ),
    )

_log_purge_schedule = tasks_settings.LOG_PURGE_INTERVAL
if _log_purge_schedule is not None:
    SYSTEM_PERIODIC_TASKS.append(
        SystemPeriodicTaskSchedule(
            schedule=_log_purge_schedule,
            tasks=[
                SystemPeriodicTaskData(
                    name="tasks__purge_task_history_logs",
                    task_name="app.tasks.celery.purge_task_history_logs",
                ),
            ],
        ),
    )


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


async def verify_taskhistory_execution_request_is_jsonb() -> None:
    """Fail fast if ``taskhistory.execution_request`` is not ``jsonb`` on PostgreSQL.

    Defend against a deploy that ships the ``@>`` dispatch dedup code
    without running the corresponding Alembic migration. ``compare_type``
    intentionally suppresses the ``json``/``jsonb`` diff during autogeneration,
    so ``make checkmigrations`` cannot detect this skew. Without this guard,
    the first dispatch hits ``operator does not exist: json @> jsonb`` at
    runtime; with it, the Tasks app refuses to start until the column is
    converted. The check is a no-op on SQLite and MySQL, where the corresponding
    migration is also a no-op.

    Use SQLAlchemy's reflection inspector rather than a raw
    ``information_schema`` query so the dialect-specific type mapping is what
    decides whether the column is ``JSONB`` or plain ``JSON``.

    :raises RuntimeError: If the PostgreSQL column type is not ``jsonb``.
    """
    if not engine.dialect.name.startswith(DatabaseDialect.POSTGRESQL):
        return
    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_columns("taskhistory")
        )
    for column in columns:
        if column["name"] != "execution_request":
            continue
        if isinstance(column["type"], JSONB):
            return
        raise RuntimeError(
            f"taskhistory.execution_request is {type(column['type']).__name__!r}, "
            "expected 'JSONB'. Run the Tasks API Alembic migrations (SEP-988) "
            "before starting the app."
        )
    raise RuntimeError(
        "taskhistory.execution_request column not found. Run the Tasks API "
        "Alembic migrations (SEP-988) before starting the app."
    )
