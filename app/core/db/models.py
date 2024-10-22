"""Define base database models."""

from datetime import datetime, UTC
from uuid import uuid4

from pydantic import UUID4
from sqlalchemy import DateTime, func, Integer
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

DateTimeWithTimezone = DateTime(timezone=True)


class BaseSQLModel(SQLModel):
    """Define a base model for database tables with common fields.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: datetime
    :param updated_at: The timestamp when the record was last updated. Automatically
        updated on changes.
    :type updated_at: datetime | None
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

    :param id: The primary key for the table. Automatically generated using UUID4.
    :type id: UUID4
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: datetime
    :param updated_at: The timestamp when the record was last updated. Automatically
        updated on changes.
    :type updated_at: datetime | None
    """

    id: UUID4 = SQLField(
        default_factory=uuid4,
        sa_column_kwargs={"primary_key": True, "autoincrement": False},
    )
