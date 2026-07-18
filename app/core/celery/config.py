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
from pydantic import ConfigDict, Field, field_validator, model_validator

from app.core.models import BaseLowercaseModel
from app.core.utils.fields import StrCredentialAnyUrl, StrDatabaseUrl, StrRelativePath

#: Service modules seeding the Celery ``include`` base. Not ``SEP.APPS`` apps, so
#: they are not registry-derived; ``build_celery_include`` prepends them.
STATIC_CELERY_INCLUDE: tuple[str, ...] = ("app.tasks.celery",)

#: Pool kwargs the celery-beat scheduler forwards to ``create_engine``.
BEAT_ENGINE_OPTION_KEYS: frozenset[str] = frozenset(
    {"pool_size", "max_overflow", "pool_timeout"}
)

#: Beat pool keys that must be whole integers; ``pool_timeout`` alone may be
#: fractional. Mirrors the ``int`` typing of the ``DatabaseOptions`` counterparts.
BEAT_ENGINE_INTEGER_KEYS: frozenset[str] = frozenset({"pool_size", "max_overflow"})


class CeleryOptions(BaseLowercaseModel):
    """Define configuration settings for Celery.

    Any extra fields passed to this model will be used for configuring Celery.

    :param broker_url: The URL of the message broker.
    :param task_track_started: Whether to track when tasks start. Defaults to True.
    :param result_backend: The URL of the result backend. Defaults to None.
    :param beat_dburi: The database URI for storing scheduled tasks. Defaults to
        ``"sqlite:///schedule.db"``.
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
        default so standalone deployments keep SQLAlchemy's own defaults; the
        installer sets it only for the forked side-car beat.
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
    beat_engine_options: dict[str, int | float] = Field(default_factory=dict)

    @field_validator("beat_engine_options")
    @classmethod
    def validate_beat_engine_options(
        cls, value: dict[str, int | float]
    ) -> dict[str, int | float]:
        """Validate beat pool options against the known pool kwargs and bounds.

        The scheduler forwards this dict straight to ``create_engine``; validating
        here surfaces a typo, wrong-shape value, or out-of-range value at config
        load rather than as a silent no-op or a late engine-creation error. Type
        and bounds mirror ``DatabaseOptions`` -- ``pool_size``/``max_overflow`` are
        whole integers, ``pool_timeout`` may be fractional -- and admit
        ``max_overflow=0`` (no overflow).

        :param value: The raw ``beat_engine_options`` mapping.
        :return: The validated mapping.
        :raises ValueError: If a key is unknown, a whole-integer key is fractional,
            or a value is out of range.
        """
        unknown = set(value) - BEAT_ENGINE_OPTION_KEYS
        if unknown:
            raise ValueError(
                f"Unknown beat_engine_options keys: {sorted(unknown)}. "
                f"Allowed keys: {sorted(BEAT_ENGINE_OPTION_KEYS)}."
            )
        fractional = sorted(
            key
            for key in BEAT_ENGINE_INTEGER_KEYS & value.keys()
            if isinstance(value[key], float) and not value[key].is_integer()
        )
        if fractional:
            raise ValueError(
                f"beat_engine_options must be whole integers, got fractional: "
                f"{fractional}."
            )
        if "pool_size" in value and value["pool_size"] < 1:
            raise ValueError("beat_engine_options 'pool_size' must be >= 1.")
        if "max_overflow" in value and value["max_overflow"] < 0:
            raise ValueError("beat_engine_options 'max_overflow' must be >= 0.")
        if "pool_timeout" in value and value["pool_timeout"] <= 0:
            raise ValueError("beat_engine_options 'pool_timeout' must be > 0.")
        return value

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
