"""Define database utilities."""

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine
from sqlalchemy.orm import sessionmaker
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
