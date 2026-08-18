# Copyright (C) 2026 Percona LLC
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

"""Define Celery settings."""

from typing import Annotated, Self

from annotated_types import Ge
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

from app.core.models import BaseLowercaseModel
from app.core.utils.fields import StrCredentialAnyUrl, StrDatabaseUrl, StrRelativePath

#: Modules seeding the Celery ``include`` base. Not ``SEP.APPS`` apps, so they are
#: not registry-derived; ``build_celery_include`` prepends them. Every entry must
#: register regardless of which apps an image ships -- the tasks service, the
#: library-owned snippet ingestion, the drain reconciler whose beat row is
#: seeded unconditionally, and the SEP-side settings-override refresher.
STATIC_CELERY_INCLUDE: tuple[str, ...] = (
    "app.tasks.celery",
    "app.sep.snippets.celery",
    "app.sep.app_drain",
    "app.sep.settings_override",
)


class PoolEngineOptions(BaseModel):
    """Define validated SQLAlchemy pool options for the celery-beat engines.

    Extra keys are rejected so a typo surfaces at config load rather than as a
    silent no-op; whole-integer coercion and the bounds mirror the
    ``DatabaseOptions`` pool counterparts (``pool_size``/``max_overflow`` are whole
    integers, ``pool_timeout`` may be fractional).

    :param pool_size: Maximum number of persistent pool connections. Must be
        ``>= 1``.
    :param max_overflow: Connections allowed beyond ``pool_size``. ``0`` disables
        overflow.
    :param pool_timeout: Seconds to wait for a free connection. Must be ``> 0``.
    """

    model_config = ConfigDict(extra="forbid")
    pool_size: PositiveInt | None = None
    max_overflow: NonNegativeInt | None = None
    pool_timeout: PositiveFloat | None = None


class CeleryOptions(BaseLowercaseModel):
    """Define configuration settings for Celery.

    Any extra fields passed to this model will be used for configuring Celery.

    :param broker_url: The URL of the message broker.
    :param task_track_started: Whether to track when tasks start. Defaults to True.
    :param result_backend: The URL of the result backend. Defaults to None.
    :param beat_dburi: The database URI for storing scheduled tasks. Defaults to
        ``"sqlite:///schedule.db"`` for a bare ``CeleryOptions``; under ``Settings``
        a lower-priority source supplies the resolved SEP database connection, so
        the beat store follows ``SEP__DATABASE__*`` unless something configures it.
    :param worker_state_db: Filesystem path where the Celery worker persists state
        such as revoked task ids. Defaults to ``.celery_worker_state``.
    :param beat_schema: The schema to store the beat tables in the database.
    :param max_retries: The maximum number of times to retry failed tasks. Defaults
        to ``0`` (no retries).
    :param global_expire_seconds: The number of seconds after which a periodic task
        will no longer run. Defaults to ``30``.
    :param beat_engine_options: SQLAlchemy pool options (``pool_size``,
        ``max_overflow``, ``pool_timeout``) for both celery-beat-database engines
        -- the async worker engine and the sync beat scheduler engine. Empty by
        default: the non-forked path runs on ``NullPool``, which rejects
        ``max_overflow`` outright and silently drops the other two, so only a
        deployment running a forked beat should set it.
    """

    model_config = ConfigDict(extra="allow")
    broker_url: StrCredentialAnyUrl
    task_track_started: bool = True
    result_backend: StrCredentialAnyUrl | None = None
    beat_dburi: StrDatabaseUrl = "sqlite:///schedule.db"
    worker_state_db: StrRelativePath = Field(
        ".celery_worker_state", validate_default=True
    )
    beat_schema: str | None = None
    max_retries: Annotated[int, Ge(0)] = 0
    global_expire_seconds: Annotated[int, Ge(0)] = 30
    beat_engine_options: PoolEngineOptions = Field(default_factory=PoolEngineOptions)

    @field_serializer("beat_engine_options")
    def serialize_beat_engine_options(
        self, value: PoolEngineOptions
    ) -> dict[str, int | float]:
        """Dump only the explicitly-set pool options as plain kwargs.

        ``model_dump`` feeds both ``Celery(**...)`` and the worker engine, so unset
        fields must be omitted -- forwarding ``None`` pool kwargs would override
        SQLAlchemy's own defaults instead of leaving them untouched.

        :param value: The validated pool options.
        :return: The set pool options keyed by their lowercase engine-kwarg names.
        """
        return value.model_dump(exclude_none=True)

    @model_validator(mode="after")
    def set_default_beat_schema(self) -> Self:
        """Ensure beat_schema is None for SQLite.

        :return: Validated options.
        :rtype: CeleryOptions
        """
        if self.beat_dburi.startswith("sqlite://"):
            self.beat_schema = None
        return self

    @model_validator(mode="after")
    def set_include(self) -> Self:
        """Seed ``include`` with the static service base.

        Reaching the app registry here would force ``sep_settings`` mid-construction,
        re-entering the same un-guarded lazy proxy that is building this ``Settings``.
        The registry-derived app modules are appended later, at a safe seam, via
        :func:`app.sep.apps.framework.registry.build_celery_include`.

        :return: Validated options with the static include base set.
        """
        self.include = list(STATIC_CELERY_INCLUDE)
        return self
