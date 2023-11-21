"""
Task API data models
"""
from datetime import (
    datetime,
    timezone,
)
from enum import IntEnum

from pydantic import BaseModel
from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    LargeBinary,
    String,
    Table,
    UniqueConstraint,
)

from sep.core.db import (
    DATABASE_EXTRA_COLUMNS,
    get_metadata,
)


class TaskBackendEnum(IntEnum):
    """
    Control the choice of backends
    """
    nomad = 1


class TaskBaseModel(BaseModel):
    """
    Model for tasks
    """
    name: str
    data: bytes

    backend: TaskBackendEnum = TaskBackendEnum.nomad

    created_at: datetime = datetime.now(tz=timezone.utc)
    deleted_at: datetime | None = None
    updated_at: datetime | None = None


class Task(TaskBaseModel):
    """
    Model for existing tasks
    """
    id: int


tasks = Table(
    "tasks",
    get_metadata(),
    Column("id", BigInteger().with_variant(Integer, dialect_name="sqlite"),
           autoincrement=True, nullable=False, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("data", LargeBinary, nullable=False),
    UniqueConstraint("name"),
)

history = Table(
    "tasks_history",
    get_metadata(),

    Column("id", BigInteger().with_variant(Integer, dialect_name="sqlite"),
           autoincrement=True, nullable=False, primary_key=True),
    Column("data", LargeBinary, nullable=False),
)

for col in DATABASE_EXTRA_COLUMNS:
    tasks.append_column(col.copy())
    history.append_column(col.copy())
