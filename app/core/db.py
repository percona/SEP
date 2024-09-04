"""Database abstraction and tooling"""

import copy
import json
import logging
from datetime import datetime
from datetime import UTC
from typing import Any
from typing import Dict
from typing import Optional
from typing import Union

from databases import Database as BaseDatabase
from fastapi import Query
from pydantic import BaseModel
from pydantic import Field
from pydantic.json import pydantic_encoder
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import MetaData
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql import ClauseElement

logger = logging.getLogger(__name__)


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

QUERY_FILTERS = {"status": ["*"], "owner": ["*"]}


def get_timestamp() -> datetime:
    """Get the current time in UTC

    :return: the current time in UTC
    :rtype: datetime
    """
    return datetime.now(tz=UTC)


class Database(BaseDatabase):
    """Database with some extra sparkles"""

    engine: AsyncEngine
    metadata: MetaData

    async def execute(
        self,
        query: Union[ClauseElement, str],
        values: Optional[dict] = None,
        last_row_id: bool = True,
    ) -> Any:
        if not self.is_connected:
            await self.connect()
        async with self.engine.begin() as dbc:
            data = await dbc.execute(query, values)
            return data.lastrowid if data and last_row_id else data


class DbBaseModel(BaseModel):
    """Base model for Pydantic databases."""

    id: int | None = None

    created_at: datetime = Field(default_factory=get_timestamp)
    deleted_at: datetime | None = None
    updated_at: datetime | None = None

    @staticmethod
    def json_serialize(*args, **kwargs) -> str:
        """Handle JSON serialization with Pydantic's encoder

        :return:
        """
        logger.debug("Serializing data: %r, %r", args, kwargs)
        return json.dumps(*args, default=pydantic_encoder, **kwargs)


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
    if isinstance(metadata, MetaData):
        database.metadata = metadata

    if not hasattr(database, "engine"):
        database.engine = get_engine(
            database.url,
            connect_args=DEFAULT_DATABASE_CONNECT_ARGS,
        )
    if database.metadata.bind != database.engine:
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


def get_database(dsn: str | bytes, include_engine=True) -> Database:
    """Create a database instance

    :param dsn: the data source, including the driver
    :type dsn: str | bytes
    :param include_engine: whether to prepare the engine
    :type include_engine: bool
    :return: the database instance
    :rtype: databases.Database
    """
    logger.debug("Acquiring database")
    if dsn in [b"", "", None]:
        raise ValueError("The DSN is empty")
    if "://" not in dsn:
        raise ValueError("The DSN is invalid")
    db = Database(dsn)
    if include_engine:
        db.engine = get_engine(dsn, connect_args=DEFAULT_DATABASE_CONNECT_ARGS)
        db.metadata = get_metadata()
        db.metadata.bind = db.engine
    logger.debug("Engine: %s", db.engine.url)
    logger.debug("Serializer: %s", db.engine.dialect._json_serializer)
    return db


def get_engine(dsn: str | bytes, connect_args: Dict[str, Any]) -> AsyncEngine:
    """Create an engine instance

    :param dsn: the data source, including the driver
    :type dsn: str | bytes
    :param connect_args: options to pass to create the engine instance
    :type connect_args: dict | None
    :return:
    """
    return create_async_engine(
        dsn,
        connect_args=connect_args,
        json_serializer=DbBaseModel.json_serialize,
    )


def get_metadata() -> MetaData:
    """Create a metadata instance

    :return:
    :rtype: sqlalchemy.MetaData
    """
    return MetaData()


def get_filtered_query(
    filters: dict,
    query: Query,
    table: Table,
    mapping: dict,
) -> Query:
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
        if value not in QUERY_FILTERS[field] and "*" not in QUERY_FILTERS[field]:
            continue
        # TODO: temporary solution for JSON querying of the tasks.meta.owner
        if field == "owner" and table.name == "tasks":
            filtered_query = filtered_query.where(
                func.json_extract(table.c.meta, "$.owners") == f'["{value}"]',
            )
            continue
        if field not in table.columns:
            continue
        if value not in mapping:
            continue
        filtered_query = filtered_query.where(table.columns[field] == mapping[value])
    return filtered_query
