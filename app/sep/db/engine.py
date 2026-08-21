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

"""Define database initialization and utility functions for SEP."""

__all__ = ["engine", "get_async_session_maker"]

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.db.utils import (
    create_app_async_engine,
    get_async_session_maker_from_engine,
)
from app.sep.config import sep_settings
from app.sep.om.config import om_schema_translate_map

# OM's tables declare a symbolic ``om_schema`` (app/sep/om/config.py); this is
# where it becomes a real schema, or the default one. It belongs on the engine rather
# than at the call sites because both paths that reach OM's tables come from here:
# the routes through ``SessionDep`` and the Celery task through
# ``get_async_session_maker``. One option therefore covers the HTTP path and the
# background path together -- which is the whole reason a schema was affordable where
# a second database would not have been.
engine = create_app_async_engine(sep_settings.DATABASE).execution_options(
    schema_translate_map=om_schema_translate_map(sep_settings.DATABASE)
)


def get_async_session_maker() -> async_sessionmaker:
    """Return a new asynchronous session maker for database operations.

    This function creates a new SQLAlchemy asynchronous session maker using the
    predefined engine configuration.

    :return: A new asynchronous session maker.
    :rtype: sessionmaker
    """
    return get_async_session_maker_from_engine(engine)
