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
from sqlalchemy import JSON
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.sql import column

from app.core.db.utils import func_json_extract, get_async_session_maker_from_engine


@pytest.mark.asyncio
async def test_get_async_session_maker_from_engine():
    """Verify that the sessionmaker is correctly configured with AsyncSession and expire_on_commit=False."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    session_maker = get_async_session_maker_from_engine(engine)
    assert session_maker.kw.get("expire_on_commit") is False

    async with session_maker() as session:
        assert isinstance(session, AsyncSession)


def _compile(expr, dialect) -> str:
    return str(expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def test_func_json_extract_postgresql_single_key_renders_double_arrow():
    """Render ``execution_request->>'task'`` for a single-element path on PostgreSQL."""
    json_column = column("execution_request", type_=JSON)

    expression = func_json_extract("postgresql", json_column, "task")

    rendered = _compile(expression, postgresql.dialect())
    assert "->>" in rendered
    assert "'task'" in rendered
    assert "json_extract_path_text" not in rendered
    assert "CAST" not in rendered.upper()


def test_func_json_extract_postgresql_nested_path_renders_arrow_chain():
    """Chain ``->`` then ``->>`` for a nested path on PostgreSQL."""
    json_column = column("execution_request", type_=JSON)

    expression = func_json_extract("postgresql", json_column, "meta", "key")

    rendered = _compile(expression, postgresql.dialect())
    assert "->" in rendered
    assert "->>" in rendered
    assert "'meta'" in rendered
    assert "'key'" in rendered
    assert rendered.index("->") < rendered.index("->>")
    assert "json_extract_path_text" not in rendered


def test_func_json_extract_sqlite_single_key_renders_json_extract():
    """Render ``json_extract(col, '$.task')`` on SQLite for a single-element path."""
    json_column = column("execution_request", type_=JSON)

    expression = func_json_extract("sqlite", json_column, "task")

    rendered = _compile(expression, sqlite.dialect())
    assert "json_extract" in rendered.lower()
    assert "'$.task'" in rendered


def test_func_json_extract_sqlite_nested_path_renders_dotted_path():
    """Render ``json_extract(col, '$.meta.key')`` on SQLite for a nested path."""
    json_column = column("execution_request", type_=JSON)

    expression = func_json_extract("sqlite", json_column, "meta", "key")

    rendered = _compile(expression, sqlite.dialect())
    assert "json_extract" in rendered.lower()
    assert "'$.meta.key'" in rendered


def test_func_json_extract_mysql_single_key_renders_json_extract():
    """Render ``json_extract(col, '$.task')`` on MySQL for a single-element path."""
    json_column = column("execution_request", type_=JSON)

    expression = func_json_extract("mysql", json_column, "task")

    rendered = _compile(expression, mysql.dialect())
    assert "json_extract" in rendered.lower()
    assert "'$.task'" in rendered
