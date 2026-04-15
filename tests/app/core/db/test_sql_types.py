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

"""Define tests for the app.core.db.sql_types module."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db.sql_types import AutoJSON


class TestAutoJSON:
    """Test the AutoJSON TypeDecorator."""

    def test_load_dialect_impl_postgresql(self):
        """Assert JSONB is used for the PostgreSQL dialect."""
        auto_json = AutoJSON()
        dialect = MagicMock()
        dialect.name = "postgresql"
        dialect.type_descriptor = lambda t: t

        result = auto_json.load_dialect_impl(dialect)

        assert isinstance(result, JSONB)

    @pytest.mark.parametrize("dialect_name", ["mysql", "sqlite"])
    def test_load_dialect_impl_non_postgresql(self, dialect_name):
        """Assert JSON is used for non-PostgreSQL dialects.

        :param dialect_name: The dialect name to test.
        :type dialect_name: str
        """
        auto_json = AutoJSON()
        dialect = MagicMock()
        dialect.name = dialect_name
        dialect.type_descriptor = lambda t: t

        result = auto_json.load_dialect_impl(dialect)

        assert isinstance(result, JSON)

    def test_cache_ok(self):
        """Assert cache_ok is set to True."""
        assert AutoJSON.cache_ok is True
