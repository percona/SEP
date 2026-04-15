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

"""Define tests for the app.core.db.utils module."""

import pytest
from sqlalchemy import Column, Integer, MetaData, Table
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.db.utils import get_async_session_maker_from_engine, idempotent_insert


@pytest.mark.asyncio
async def test_get_async_session_maker_from_engine():
    """Verify that the sessionmaker is correctly configured with AsyncSession and expire_on_commit=False."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    session_maker = get_async_session_maker_from_engine(engine)
    assert session_maker.kw.get("expire_on_commit") is False

    async with session_maker() as session:
        assert isinstance(session, AsyncSession)


@pytest.fixture
def sample_table():
    """Return a minimal SQLAlchemy Table for dispatch tests."""
    metadata = MetaData()
    return Table("sample", metadata, Column("id", Integer, primary_key=True))


class TestIdempotentInsert:
    """Test the dialect-aware ``idempotent_insert`` helper."""

    def test_postgresql_returns_on_conflict_insert(self, sample_table):
        """Assert PostgreSQL dispatch produces an ``ON CONFLICT DO NOTHING`` insert."""
        stmt = idempotent_insert("postgresql", sample_table)
        assert isinstance(stmt, postgresql.Insert)
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        assert "ON CONFLICT DO NOTHING" in compiled.upper()

    def test_sqlite_returns_on_conflict_insert(self, sample_table):
        """Assert SQLite dispatch produces an ``ON CONFLICT DO NOTHING`` insert."""
        stmt = idempotent_insert("sqlite", sample_table)
        assert isinstance(stmt, sqlite.Insert)
        compiled = str(stmt.compile(dialect=sqlite.dialect()))
        assert "ON CONFLICT DO NOTHING" in compiled.upper()

    def test_mysql_returns_insert_ignore(self, sample_table):
        """Assert MySQL dispatch produces an ``INSERT IGNORE`` statement."""
        stmt = idempotent_insert("mysql", sample_table)
        assert isinstance(stmt, mysql.Insert)
        compiled = str(stmt.compile(dialect=mysql.dialect()))
        assert "INSERT IGNORE" in compiled.upper()

    def test_unknown_dialect_raises(self, sample_table):
        """Assert an unsupported dialect raises ``NotImplementedError``."""
        with pytest.raises(NotImplementedError, match="oracle"):
            idempotent_insert("oracle", sample_table)
