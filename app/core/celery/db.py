# Copyright (C) 2026 Percona LLC
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

"""Define database initialization and utility functions for the Celery scheduler."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer, run_pydantic_type_validator
from app.core.utils.fields import StrAsyncDatabaseUrl

engine = create_async_engine(
    run_pydantic_type_validator(StrAsyncDatabaseUrl, settings.CELERY.beat_dburi),
    echo=False,
    json_serializer=json_serializer,
    **settings.CELERY.beat_engine_options,
).execution_options(schema_translate_map={"celery_schema": settings.CELERY.beat_schema})


def get_async_session_maker() -> async_sessionmaker:
    """Return a new asynchronous session maker for database operations.

    This function creates a new SQLAlchemy asynchronous session maker using the
    predefined engine configuration.

    :return: A new asynchronous session maker.
    :rtype: sessionmaker
    """
    return get_async_session_maker_from_engine(engine)
