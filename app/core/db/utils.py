"""Define database utilities."""

from sqlalchemy import cast, Column, ColumnClause, func, Function, JSON
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine
from sqlalchemy.orm import InstrumentedAttribute, sessionmaker
from sqlmodel import col
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
