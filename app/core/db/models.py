"""Define base database models."""

from datetime import datetime
from datetime import UTC
from uuid import uuid4

from pydantic import UUID4
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import Integer
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

DateTimeWithTimezone = DateTime(timezone=True)


class BaseSQLModel(SQLModel):
    """Define a base model for database tables with common fields.

    Attributes
    ----------
    id : int or None
        The primary key for the table. Auto-incremented and not nullable.
    created_at : datetime
        The timestamp when the record is created. Defaults to the current time in UTC.
    updated_at : datetime or None
        The timestamp when the record is last updated. Automatically updated on changes.

    """

    id: int | None = SQLField(
        nullable=False,
        sa_type=Integer,
        sa_column_kwargs={"primary_key": True, "autoincrement": True},
    )
    created_at: datetime = SQLField(
        sa_type=DateTimeWithTimezone,
        default_factory=lambda: datetime.now(UTC),
    )
    updated_at: datetime | None = SQLField(
        default=None,
        sa_type=DateTimeWithTimezone,
        sa_column_kwargs={"onupdate": func.now()},
    )


class BaseUUIDSQLModel(BaseSQLModel):
    """Define a base model for database tables with a UUID primary key.

    This base model extends `BaseSQLModel` by replacing the integer `id` with a UUID,
    providing a universally unique identifier for each record. It is useful for
    scenarios where a non-sequential, hard-to-guess primary key is desirable.

    Attributes
    ----------
    id : UUID4
        The primary key for the table. Automatically generated using UUID4.
    created_at : datetime
        The timestamp when the record is created. Defaults to the current time in UTC.
    updated_at : datetime or None
        The timestamp when the record is last updated. Automatically updated on changes.

    """

    id: UUID4 = SQLField(
        default_factory=uuid4,
        sa_column_kwargs={"primary_key": True, "autoincrement": False},
    )
