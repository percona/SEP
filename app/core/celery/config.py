"""Define Celery settings."""

from typing import Annotated, Self

from annotated_types import Ge
from pydantic import ConfigDict, model_validator

from app.core.models import BaseLowercaseModel
from app.core.utils.fields import StrAnyUrl, StrDatabaseUrl


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
    :param beat_schema: The schema to store the beat tables in the database.
    :type beat_schema: str | None
    :param max_retries: The maximum number of times to retry failed tasks. Defaults
        to `0` (no retries).
    :type max_retries: int
    :param global_expire_seconds: The number of seconds after which a periodic task
        will no longer run. Defaults to `30`.
    :type global_expire_seconds: int
    """

    model_config = ConfigDict(extra="allow")
    broker_url: StrAnyUrl
    task_track_started: bool = True
    result_backend: StrAnyUrl | None = None
    beat_dburi: StrDatabaseUrl = "sqlite:///schedule.db"
    beat_schema: str | None = None
    max_retries: Annotated[int, Ge(0)] = 0
    global_expire_seconds: Annotated[int, Ge(0)] = 30

    @model_validator(mode="after")
    def set_default_beat_schema(self) -> Self:
        """Ensure beat_schema is None for SQLite.

        :return: Validated options.
        :rtype: CeleryOptions
        """
        if self.beat_dburi.startswith("sqlite://"):
            self.beat_schema = None
        return self
