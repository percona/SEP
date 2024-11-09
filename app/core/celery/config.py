"""Define Celery settings."""

from pydantic import ConfigDict

from app.core.fields import StrAnyUrl, StrDatabaseUrl
from app.core.models import BaseLowercaseModel


class CeleryOptions(BaseLowercaseModel):
    """Define configuration settings for Celery.

    Any extra fields passed to this model will be used for configuring Celery.

    :param broker_url: The URL of the message broker.
    :type broker_url: StrAnyUrl
    :param task_track_started: Whether to track when tasks start. Defaults to True.
    :type task_track_started: bool
    :param result_backend: The URL of the result backend. Defaults to None.
    :type result_backend: StrAnyUrl | None
    :param beat_dburi: The database URI for storing scheduled tasks. Defaults to
        `"sqlite:///schedule.db"`.
    :type beat_dburi: StrDatabaseUrl
    """

    model_config = ConfigDict(extra="allow")
    broker_url: StrAnyUrl
    task_track_started: bool = True
    result_backend: StrAnyUrl | None = None
    beat_dburi: StrDatabaseUrl = "sqlite:///schedule.db"
