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

"""Define database utilities."""

from typing import Any

from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, ColumnClause, ColumnElement, func, JSON, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine
from sqlalchemy.orm import InstrumentedAttribute, sessionmaker
from sqlalchemy.sql.type_api import TypeEngine
from sqlmodel import AutoString, col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.sql_types import AutoJSON
from app.core.utils.fields import DatabaseDialect

SQLAlchemyColumn = ColumnClause | Column | InstrumentedAttribute


def get_async_session_maker_from_engine(engine: AsyncEngine) -> async_sessionmaker:
    """Return a new asynchronous session maker for database operations.

    This function creates a new SQLAlchemy asynchronous session maker using the
    predefined engine configuration.

    :param engine: The SQLAlchemy asynchronous engine to bind the session maker to.
    :type engine: AsyncEngine
    :return: A new asynchronous session maker.
    :rtype: async_sessionmaker
    """
    return sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def json_join_path_elems(*path_elems: str) -> str:
    """Join JSON path elements into a single string.

    :param path_elems: The JSON path elements to join.
    :type path_elems: str
    :return: The joined JSON path string.
    :rtype: str
    """
    json_path = "$"
    for elem in path_elems:
        if elem.isdigit():
            json_path += f"[{elem}]"
        else:
            json_path += f".{elem}"
    return json_path


def func_json_extract(
    db_engine: str, json_column: SQLAlchemyColumn, *path_elems: str
) -> ColumnElement:
    """Render a dialect-specific JSON scalar extraction expression.

    Emit SQL whose shape matches the expression indexes created for
    ``taskhistory.execution_request`` so the planner can use them:

    - PostgreSQL: ``col->'a'->>'b'``. The final ``->>`` returns the value as
      text. The expression is valid on both ``json`` and ``jsonb`` columns.
    - SQLite: ``json_extract(col, '$.a.b')``. SQLite auto-unquotes scalars, so
      the result is directly comparable to a string.
    - MySQL: ``json_extract(col, '$.a.b')``. No functional index is created on
      MySQL because a width-limited ``CAST`` would introduce comparison
      truncation; MySQL dev environments fall back to non-indexed filtering.

    :param db_engine: The database engine type (e.g., ``"postgresql"``).
    :type db_engine: str
    :param json_column: The JSON column to extract the value from.
    :type json_column: SQLAlchemyColumn
    :param path_elems: The JSON path elements to extract.
    :type path_elems: str
    :return: A SQL expression whose value is comparable to a string.
    :rtype: ColumnElement
    """
    column = col(json_column)
    if db_engine.startswith(DatabaseDialect.POSTGRESQL):
        expression = column
        for elem in path_elems[:-1]:
            expression = expression.op("->")(elem)
        return expression.op("->>")(path_elems[-1])
    return func.json_extract(column, json_join_path_elems(*path_elems))


def prepare_unsafe_value_for_json_comparison(db_engine: str, value: Any) -> Any:
    """Prepare a value for JSON comparison based on the database engine.

    On PostgreSQL the text operator ``->>`` returns JSON scalars as text, so we
    convert the value to a string for comparison. For other databases, we return
    the value as is.

    :param db_engine: The database engine type (e.g., "postgresql").
    :type db_engine: str
    :param value: The value to prepare for comparison.
    :type value: Any
    :return: The prepared value for JSON comparison.
    :rtype: Any
    """
    if db_engine.startswith(DatabaseDialect.POSTGRESQL):
        return str(value)
    return value


def compare_type(
    context: MigrationContext,  # noqa: ARG001
    inspected_column: Column,  # noqa: ARG001
    metadata_column: Column,  # noqa: ARG001
    inspected_type: TypeEngine,
    metadata_type: TypeEngine,
) -> bool | None:
    """Suppress spurious Alembic type diffs for known equivalent type pairs.

    :param context: The Alembic migration context.
    :type context: MigrationContext
    :param inspected_column: The column object as inspected from the database.
    :type inspected_column: Column
    :param metadata_column: The column object as defined in the model's metadata.
    :type metadata_column: Column
    :param inspected_type: The type of the column as determined by the database
        inspector.
    :type inspected_type: TypeEngine
    :param metadata_type: The type of the column as defined in the model's metadata.
    :type metadata_type: TypeEngine
    :return: False if the types are equivalent and no migration is needed;
        None to fall through to default comparison.
    :rtype: bool | None
    """
    if isinstance(inspected_type, Text) and isinstance(metadata_type, AutoString):
        return False
    if isinstance(metadata_type, AutoJSON) and isinstance(inspected_type, JSONB | JSON):
        return False
    return None
