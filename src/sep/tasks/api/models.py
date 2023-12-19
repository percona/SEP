"""
Task API data models
"""
from datetime import (
    datetime,
    timezone,
)
from enum import IntEnum
import json

from pydantic import BaseModel
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
    TypeDecorator,
    UniqueConstraint,
)

from sep.core.db import (
    DATABASE_EXTRA_COLUMNS,
    get_metadata,
)

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


class TaskBaseModel(BaseModel):
    """
    Model for tasks
    """

    name: str
    data: str

    backend: TaskBackendEnum = TaskBackendEnum.nomad

    created_at: datetime = datetime.now(tz=timezone.utc)
    deleted_at: datetime | None = None
    updated_at: datetime | None = None


class Task(TaskBaseModel):
    """
    Model for existing tasks
    """

    id: int


class TaskHistoryDataType(TypeDecorator):
    """Data type for task history data"""

    impl = JSON

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = json.loads(value)
        return value


class TaskHistoryBaseModel(BaseModel):
    """Model for task history"""

    name: str
    data: str
    status: int = TASK_HISTORY_STATUS_MAP["pending"]

    created_at: datetime = datetime.now(tz=timezone.utc)
    deleted_at: datetime | None = None
    updated_at: datetime | None = None


class TaskHistory(TaskHistoryBaseModel):
    """Model for existing task history"""

    id: int


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
    Column("data", TaskHistoryDataType, nullable=False),
    Column("status", Enum(TaskHistoryStatusEnum).with_variant(Integer, dialect_name="sqlite"), nullable=False),
)

Index("task_name", history.name)

for col in DATABASE_EXTRA_COLUMNS:
    tasks.append_column(col.copy())
    history.append_column(col.copy())
