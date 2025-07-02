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

"""Define database utilities."""

from alembic.runtime.migration import MigrationContext
from sqlalchemy import cast, Column, ColumnClause, func, Function, JSON, Text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine
from sqlalchemy.orm import InstrumentedAttribute, sessionmaker
from sqlalchemy.sql.type_api import TypeEngine
from sqlmodel import AutoString, col
from sqlmodel.ext.asyncio.session import AsyncSession

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
) -> Function:
    """Extract a value from a JSON column using the specified path.

    :param db_engine: The database engine type (e.g., "postgresql").
    :type db_engine: str
    :param json_column: The JSON column to extract the value from.
    :type json_column: SQLAlchemyColumn
    :param path_elems: The JSON path elements to extract.
    :type path_elems: str
    :return: The SQL function for extracting the value from the JSON column.
    :rtype: Function
    """
    if db_engine.startswith("postgresql"):
        return func.json_extract_path_text(cast(col(json_column), JSON), *path_elems)
    return func.json_extract(col(json_column), json_join_path_elems(*path_elems))


def compare_type(
    context: MigrationContext,  # noqa: ARG001
    inspected_column: Column,  # noqa: ARG001
    metadata_column: Column,  # noqa: ARG001
    inspected_type: TypeEngine,
    metadata_type: TypeEngine,
) -> bool | None:
    """Define custom comparison to ensure Text type is not converted to AutoString.

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
    :return: False if the inspected type is Text and the metadata type is AutoString,
        indicating no change is required; otherwise, None.
    :rtype: bool | None
    """
    if isinstance(inspected_type, Text) and isinstance(metadata_type, AutoString):
        return False
    return None
