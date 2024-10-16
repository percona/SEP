"""Define database initialization and utility functions for the Tasks API."""

import json
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.db.utils import json_serializer
from app.tasks.config import tasks_settings
from app.tasks.models import Task
from app.tasks.models import TaskExecutionRequest

logger = logging.getLogger(__name__)


def json_deserialize(raw_data: str) -> Any:
    """Deserialize a JSON string into a Python object.

    Attempts to deserialize the input string into a `TaskExecutionRequest` model.
    If validation fails, the raw JSON data is returned as a dictionary.

    :param raw_data: The JSON string to deserialize.
    :type raw_data: str
    :return: A `TaskExecutionRequest` object if deserialization is successful,
        otherwise the raw data.
    :rtype: Any
    """
    data = json.loads(raw_data)
    try:
        return TaskExecutionRequest(**data)
    except ValidationError:
        return data


engine = create_async_engine(
    tasks_settings.DATABASE.URL,
    echo=False,
    json_serializer=json_serializer,
    json_deserializer=json_deserialize,
)


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
        "MetaOptional": ["args", "requirements"],
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
                            "python3 -m venv ${NOMAD_ALLOC_DIR}/venv; ${NOMAD_ALLOC_DIR}/venv/bin/pip install -U pip ${NOMAD_META_requirements}",
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                },
                {
                    "Name": "run-script",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            "${NOMAD_ALLOC_DIR}/venv/bin/python3 ${NOMAD_TASK_DIR}/script.py ${NOMAD_META_args}",
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "DispatchPayload": {"file": "script.py"},
                },
                {
                    "Name": "clean-up",
                    "Lifecycle": {"hook": "poststop", "sidecar": False},
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "rm",
                        "args": ["-rf", "${NOMAD_ALLOC_DIR}/venv"],
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


async def init_db(session: AsyncSession) -> None:
    """Initialize the database with generic Nomad task templates.

    If the generic task templates for 'batch' or 'sysbatch' do not exist in the
    database, this function will add them.

    :param session: The SQLAlchemy asynchronous session to use for database operations.
    :type session: AsyncSession
    """
    for task in SYSTEM_TASKS:
        result = await session.exec(
            select(Task).where(Task.name == task.name),
        )
        if result.first() is None:
            logger.debug(
                "Creating task %s",
                task.name,
            )
            session.add(task)
    await session.commit()


def get_async_session_maker() -> sessionmaker:
    """Return a new asynchronous session maker for database operations.

    This function creates a new SQLAlchemy asynchronous session maker using the
    predefined engine configuration.

    :return: A new asynchronous session maker.
    :rtype: sessionmaker
    """
    return get_async_session_maker_from_engine(engine)
