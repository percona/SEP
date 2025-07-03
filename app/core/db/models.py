# Copyright (C) 2025 Percona LLC
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

"""Define base database models."""

from uuid import uuid4

from pydantic import UUID4
from sqlalchemy import DateTime, func, Integer
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from app.core.utils.date_time import utc_now
from app.core.utils.fields import UTCDatetime

DateTimeWithTimezone = DateTime(timezone=True)


class BaseSQLModel(SQLModel):
    """Define a base model for database tables with common fields.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record was last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    """

    id: int | None = SQLField(
        nullable=False,
        sa_type=Integer,
        sa_column_kwargs={"primary_key": True, "autoincrement": True},
    )
    created_at: UTCDatetime = SQLField(
        sa_type=DateTimeWithTimezone,
        default_factory=utc_now,
    )
    updated_at: UTCDatetime | None = SQLField(
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
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record was last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    """

    id: UUID4 = SQLField(
        default_factory=uuid4,
        sa_column_kwargs={"primary_key": True, "autoincrement": False},
    )
