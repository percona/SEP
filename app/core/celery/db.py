"""Define database initialization and utility functions for the Celery scheduler."""

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.fields import StrAsyncDatabaseUrl
from app.core.utils import json_serializer, run_pydantic_type_validator

engine = create_async_engine(
    run_pydantic_type_validator(StrAsyncDatabaseUrl, settings.CELERY.beat_dburi),
    echo=False,
    json_serializer=json_serializer,
).execution_options(schema_translate_map={"celery_schema": settings.CELERY.beat_schema})


def get_async_session_maker() -> sessionmaker:
    """Return a new asynchronous session maker for database operations.

    This function creates a new SQLAlchemy asynchronous session maker using the
    predefined engine configuration.

    :return: A new asynchronous session maker.
    :rtype: sessionmaker
    """
    return get_async_session_maker_from_engine(engine)
