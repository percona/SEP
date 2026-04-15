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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.sql import column
from sqlmodel import col

from app.core.db.utils import (
    compare_type,
    func_json_extract,
    get_async_session_maker_from_engine,
)
from app.tasks.models import TaskExecutionRequestJSON, TaskHistory


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


def _compile_postcompile(expr, dialect) -> str:
    return str(
        expr.compile(dialect=dialect, compile_kwargs={"render_postcompile": True})
    )


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
    meta_index = rendered.index("'meta'")
    key_index = rendered.index("'key'")
    assert "->" in rendered[:meta_index]
    assert "->>" in rendered[meta_index:key_index]
    assert meta_index < key_index
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


def test_func_json_extract_postgresql_mapped_column_binds_path_as_text():
    """Force text-typed binds for PG JSON operators on mapped ORM columns.

    SQLAlchemy infers bind parameter types from the LHS column type. Using a
    mapped JSON attribute directly would otherwise render
    ``col ->> %(param)s::JSON``, which is invalid SQL because PostgreSQL's
    ``->`` / ``->>`` operators only accept ``text`` / ``integer`` RHS operands.
    """
    mapped_column = col(TaskHistory.execution_request)

    single = func_json_extract("postgresql", mapped_column, "task")
    nested = func_json_extract("postgresql", mapped_column, "meta", "key")

    single_sql = str(single.compile(dialect=postgresql.dialect()))
    nested_sql = str(nested.compile(dialect=postgresql.dialect()))
    assert "::JSON" not in single_sql.upper()
    assert "::JSON" not in nested_sql.upper()


def test_func_json_extract_postgresql_equality_compiles_with_literal_binds():
    """Render equality comparisons with literal binds on PostgreSQL.

    The helper must return a text-typed expression so callers comparing the
    result against a string (e.g. ``extract(...) == queue_item.task``) can
    bind the RHS value as text. A JSON-typed return would try to render the
    RHS as a JSON literal and raise a ``CompileError``.
    """
    mapped_column = col(TaskHistory.execution_request)

    single = func_json_extract("postgresql", mapped_column, "task") == "mysqldump"
    nested = (
        func_json_extract("postgresql", mapped_column, "meta", "origin") == "scheduler"
    )

    single_sql = str(
        single.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    nested_sql = str(
        nested.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "'mysqldump'" in single_sql
    assert "'scheduler'" in nested_sql


def test_func_json_extract_postgresql_path_is_inlined_for_index_match():
    """Inline JSON path constants so PG expression indexes can be matched.

    PostgreSQL expression indexes like
    ``CREATE INDEX ... ON taskhistory ((execution_request->>'task'))`` only
    match queries whose arrow expression contains the same literal key, not
    a bound parameter. Render the helper with post-compile expansion to
    confirm the path element appears as an inline literal (``'task'``)
    rather than a parameter placeholder.
    """
    mapped_column = col(TaskHistory.execution_request)

    expression = func_json_extract("postgresql", mapped_column, "task")

    rendered = _compile_postcompile(expression, postgresql.dialect())
    assert "->> 'task'" in rendered or "->>'task'" in rendered


def test_func_json_extract_sqlite_path_is_inlined_for_index_match():
    """Inline JSON path constants so SQLite expression indexes can be matched.

    SQLite's ``CREATE INDEX ... ON taskhistory (json_extract(execution_request, '$.task'))``
    is only used when the query renders the same literal path. Confirm the
    helper emits ``json_extract(..., '$.task')`` rather than a parameter
    placeholder for the path argument.
    """
    json_column = column("execution_request", type_=JSON)

    expression = func_json_extract("sqlite", json_column, "task")

    rendered = _compile_postcompile(expression, sqlite.dialect())
    assert "'$.task'" in rendered
    assert "?" not in rendered


def test_compare_type_suppresses_diff_for_task_execution_request_json_against_json():
    """Suppress spurious Alembic diffs when ``TaskExecutionRequestJSON`` meets ``JSON``.

    ``compare_type`` must recognise ``TaskExecutionRequestJSON`` as a subclass
    of ``AutoJSON`` and return ``False`` so Alembic autogeneration does not
    propose a no-op type change against an inspected ``JSON`` column.
    """
    result = compare_type(
        context=None,  # type: ignore[arg-type]
        inspected_column=None,  # type: ignore[arg-type]
        metadata_column=None,  # type: ignore[arg-type]
        inspected_type=JSON(),
        metadata_type=TaskExecutionRequestJSON(),
    )
    assert result is False


def test_compare_type_suppresses_diff_for_task_execution_request_json_against_jsonb():
    """Suppress spurious Alembic diffs when ``TaskExecutionRequestJSON`` meets ``JSONB``.

    Pin the contract that flipping ``TaskExecutionRequestJSON`` to inherit
    from ``AutoJSON`` keeps autogeneration quiet against the ``jsonb`` column
    that PostgreSQL exposes after the SEP-988 migration runs.
    """
    result = compare_type(
        context=None,  # type: ignore[arg-type]
        inspected_column=None,  # type: ignore[arg-type]
        metadata_column=None,  # type: ignore[arg-type]
        inspected_type=JSONB(),
        metadata_type=TaskExecutionRequestJSON(),
    )
    assert result is False
