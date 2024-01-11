"""
Database abstraction and tooling
"""
import copy
from typing import (
    Any,
    Dict,
    Union,
)

from databases import Database
from fastapi import Query
from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    Table,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
)

DEFAULT_DATABASE_DSN = "sqlite+aiosqlite://"
DEFAULT_DATABASE_CONNECT_ARGS = {"check_same_thread": False}
DEFAULT_PREPARATION_QUERIES = {
    "sqlite": ["PRAGMA foreign_keys=OFF", "PRAGMA encoding='UTF-8'"],
}

DATABASE_EXTRA_COLUMNS = [
    Column("created_at", DateTime),
    Column("deleted_at", DateTime),
    Column("updated_at", DateTime),
]

QUERY_FILTERS = {
    'status': ['*']
}


async def startup(database: Database, metadata: Union[MetaData, None] = None):
    """Initialisation process

    :param database: the database instance
    :type database: databases.Database
    :param metadata: the metadata instance
    :type metadata: MetaData
    :return:
    """
    if not database.is_connected:
        await database.connect()

    if not hasattr(database, "metadata") and metadata is None:
        raise ValueError("metadata is not defined")
    elif isinstance(metadata, MetaData):
        database.metadata = metadata

    if not hasattr(database, "engine"):
        database.engine = get_engine(database.url, connect_args=DEFAULT_DATABASE_CONNECT_ARGS)

    database.metadata.bind = database.engine
    async with database.engine.begin() as dbc:
        await dbc.run_sync(database.metadata.create_all)


def prepare_connection(connection, record, **kwargs):
    """Prepare the database connection

    :param connection:
    :param record:
    :param kwargs:
    :return:
    """
    cursor = connection.cursor()
    queries = []
    user_queries = kwargs.get("queries", [])

    if hasattr(record.dbapi_connection.dbapi, "sqlite_version"):
        queries = DEFAULT_PREPARATION_QUERIES["sqlite"]

    for query in queries + user_queries:
        if isinstance(query, str):
            cursor.execute(query)
        elif len(query) == 1:
            cursor.execute(query[0])
        elif isinstance(query, tuple) and len(query) > 1:
            cursor.execute(query[0], query[1:])
    cursor.close()


def get_database(dsn: str | bytes) -> Database:
    """
    Create a database instance

    :param dsn: the data source, including the driver
    :type dsn: str | bytes
    :return: the database instance
    :rtype: databases.Database
    """
    if dsn in [b"", "", None]:
        raise ValueError("The DSN is empty")
    if "://" not in dsn:
        raise ValueError("The DSN is invalid")
    return Database(dsn)


def get_engine(dsn: str | bytes, connect_args: Dict[str, Any]) -> AsyncEngine:
    """
    Create an engine instance

    :param dsn: the data source, including the driver
    :type dsn: str | bytes
    :param connect_args: options to pass to create the engine instance
    :type connect_args: dict | None
    :return:
    """
    return create_async_engine(dsn, connect_args=connect_args)


def get_metadata() -> MetaData:
    """
    Create a metadata instance

    :return:
    :rtype: sqlalchemy.MetaData
    """
    return MetaData()


def get_filtered_query(filters: dict, query: Query, table: Table, mapping: dict) -> Query:
    """Apply a where clause to a query

    :param filters:
    :param query:
    :param table:
    :param mapping:
    :return:
    """
    filtered_query = copy.copy(query)
    for field, value in filters.items():
        # TODO: decide how to handle the currently bypassed scenarios
        #       options:
        #          - return the original query
        #          - raise an error
        #          - bypass and notify
        if field not in QUERY_FILTERS:
            continue
        if value not in QUERY_FILTERS[field] and '*' not in QUERY_FILTERS[field]:
            continue
        if field not in table.columns:
            continue
        if value not in mapping:
            continue
        filtered_query = filtered_query.where(table.columns[field] == mapping[value])
    return filtered_query
