"""
Database abstraction and tooling
"""
from typing import (
    Any,
    Dict,
    Union,
)

from databases import Database
from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
)

DEFAULT_DATABASE_DSN = 'sqlite+aiosqlite://'
DEFAULT_DATABASE_CONNECT_ARGS = {
    "check_same_thread": False
}

DATABASE_EXTRA_COLUMNS = [
    Column("created_at", DateTime),
    Column("deleted_at", DateTime),
    Column("updated_at", DateTime),
]


async def startup(database: Database, metadata: Union[MetaData, None] = None):
    """

    :param database: the database instance
    :type database: databases.Database
    :param metadata: the metadata instance
    :type metadata: MetaData
    :return:
    """
    if not database.is_connected:
        await database.connect()

    if not hasattr(database, 'metadata') and metadata is None:
        raise ValueError("metadata is not defined")
    elif isinstance(metadata, MetaData):
        database.metadata = metadata

    if not hasattr(database, "engine"):
        database.engine = get_engine(database.url, connect_args=DEFAULT_DATABASE_CONNECT_ARGS)

    database.metadata.bind = database.engine
    async with database.engine.begin() as dbc:
        await dbc.run_sync(database.metadata.create_all)


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
    if '://' not in dsn:
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
