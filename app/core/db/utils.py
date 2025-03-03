"""Define database utilities."""

from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, Text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.type_api import TypeEngine
from sqlmodel import AutoString
from sqlmodel.ext.asyncio.session import AsyncSession


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
