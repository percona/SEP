"""Define base database models."""

from datetime import datetime
from datetime import UTC

from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import Integer
from sqlmodel import Field
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

    id: int | None = Field(
        nullable=False,
        sa_type=Integer,
        sa_column_kwargs={"primary_key": True, "autoincrement": True},
    )
    created_at: datetime = Field(
        sa_type=DateTimeWithTimezone,
        default_factory=lambda: datetime.now(UTC),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_type=DateTimeWithTimezone,
        sa_column_kwargs={"onupdate": func.now()},
    )
