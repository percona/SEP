"""
Task API data models
"""
from datetime import (
    datetime,
    timezone,
)

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


class TaskBaseModel(BaseModel):
    """
    Model for tasks
    """
    name: str
    data: bytes

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

for col in DATABASE_EXTRA_COLUMNS:
    tasks.append_column(col)
