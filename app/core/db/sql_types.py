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

"""Define custom SQLAlchemy column types."""

from typing import Any

from sqlalchemy import JSON, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.sql.type_api import TypeEngine


class AutoJSON(TypeDecorator):
    """Resolve to JSONB on PostgreSQL and JSON on other dialects.

    :cvar impl: The base implementation type.
    :vartype impl: type[JSON]
    :cvar cache_ok: Allow SQLAlchemy to cache compiled statements using this type.
    :vartype cache_ok: bool
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        """Return the dialect-specific type implementation.

        :param dialect: The SQLAlchemy dialect in use.
        :type dialect: Dialect
        :return: JSONB for PostgreSQL, JSON for all other dialects.
        :rtype: TypeEngine[Any]
        """
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return super().load_dialect_impl(dialect)
