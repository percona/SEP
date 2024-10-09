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

    Parameters
    ----------
    raw_data : str
        The JSON string to deserialize.

    Returns
    -------
    Any
        A `TaskExecutionRequest` object if deserialization is successful,
        otherwise the raw data.

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


async def init_db(session: AsyncSession) -> None:
    """Initialize the database with generic Nomad task templates.

    If the generic task templates for 'batch' or 'sysbatch' do not exist in the
    database, this function will add them.

    Parameters
    ----------
    session : AsyncSession
        The SQLAlchemy asynchronous session to use for database operations.

    """
    for job_type in ["batch", "sysbatch"]:
        result = await session.exec(
            select(Task).where(Task.name == f"generic-nomad-{job_type}"),
        )
        task = result.first()
        if not task:
            logger.debug(
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
                data=tpl,
                is_template=True,
                protected=True,
            )
            session.add(task)
    await session.commit()


def get_async_session_maker() -> sessionmaker:
    """Return a new asynchronous session maker for database operations.

    This function creates a new SQLAlchemy asynchronous session maker using the
    predefined engine configuration.

    Returns
    -------
    sessionmaker
        A new asynchronous session maker.

    """
    return get_async_session_maker_from_engine(engine)
