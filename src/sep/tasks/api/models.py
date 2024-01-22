"""
Task API data models

TODO:
  - ensure that we can handle arbitrary parameters for invocation, which should allow mapping
    to HTML form fields to allow for dynamic rendering when executing a task via the UI
  - owner of a task, allowing app-only, general use, etc (Casdoor potentially)
    e.g. owner = tasks, owner = alters, owner = *
  - scheduled task, which can run at a specific time, or require manual invocation

"""
from datetime import datetime
from enum import IntEnum
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)
from sqlalchemy import (
    BigInteger,
    Column,
    Enum,
    Index,
    Integer,
    JSON,
    null,
    String,
    Table,
    UniqueConstraint,
)

from sep.core.db import (
    DATABASE_EXTRA_COLUMNS,
    DbBaseModel,
    get_metadata,
)
from sep.core.utils import get_timestamp

TASK_ALIAS_LENGTH = 100
TASK_BACKEND_MAP = {  # CAUTION: changing existing values should be done with the utmost care
    "nomad": 1,
}
TASK_BACKEND_LOOKUP = {v: k for k, v in TASK_BACKEND_MAP.items()}

TASK_HISTORY_STATUS_MAP = {  # CAUTION: changing existing values should be done with the utmost care
    "failed": 1,
    "pending": 2,
    "running": 3,
    "success": 0,
}
TASK_HISTORY_STATUS_LOOKUP = {v: k for k, v in TASK_HISTORY_STATUS_MAP.items()}


class TaskBackendEnum(IntEnum):
    """
    Control the choice of backends
    """

    nomad = TASK_BACKEND_MAP["nomad"]


class TaskHistoryStatusEnum(IntEnum):
    """
    Status codes
    """

    failed = TASK_HISTORY_STATUS_MAP["failed"]
    pending = TASK_HISTORY_STATUS_MAP["pending"]
    running = TASK_HISTORY_STATUS_MAP["running"]
    success = TASK_HISTORY_STATUS_MAP["success"]


class TaskExecutionRequest(BaseModel):
    """Model for execution requests"""

    model_config = ConfigDict(extra="allow")

    task: str
    target: str
    meta: Optional[dict] = {}
    tracking: Optional[dict] = {"allocation_id": None, "evaluation_id": None}


class Task(DbBaseModel):
    """
    Model for tasks
    """

    name: str
    data: str

    backend: TaskBackendEnum = TaskBackendEnum.nomad


class TaskHistory(DbBaseModel):
    """Model for task history"""

    name: str
    execution_request: TaskExecutionRequest
    data: Task
    status: int = TASK_HISTORY_STATUS_MAP["pending"]


tasks = Table(
    "tasks",
    get_metadata(),
    Column(
        "id",
        BigInteger().with_variant(Integer, dialect_name="sqlite"),
        autoincrement=True,
        nullable=False,
        primary_key=True,
    ),
    Column("name", String(TASK_ALIAS_LENGTH), nullable=False),
    Column("data", JSON, nullable=False),
    Column(
        "backend", Enum(TaskBackendEnum).with_variant(Integer, dialect_name="sqlite"), default=null(), nullable=True
    ),
    UniqueConstraint("name"),
)

history = Table(
    "tasks_history",
    get_metadata(),
    Column(
        "id",
        BigInteger().with_variant(Integer, dialect_name="sqlite"),
        autoincrement=True,
        nullable=False,
        primary_key=True,
    ),
    Column("name", String(TASK_ALIAS_LENGTH), nullable=False),
    Column("execution_request", JSON, nullable=False),
    Column("data", JSON, nullable=False),
    Column("tracking", JSON, nullable=False, default="{}"),
    Column("status", Enum(TaskHistoryStatusEnum).with_variant(Integer, dialect_name="sqlite"), nullable=False),
)

Index("task_name", history.name)

for col in DATABASE_EXTRA_COLUMNS:
    tasks.append_column(col.copy())
    history.append_column(col.copy())
