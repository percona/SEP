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
