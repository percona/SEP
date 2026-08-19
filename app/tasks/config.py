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

"""Define settings for the Tasks app."""

from datetime import timedelta
from enum import StrEnum
from typing import Annotated, ClassVar

from annotated_types import Gt, Le
from pydantic import Field, PositiveInt
from sqlalchemy_celery_beat.models import Period

from app.core.celery.models import IntervalSchedule
from app.core.config import BaseYamlAppSettings
from app.core.db.config import DatabaseOptions
from app.core.middleware.security_headers import SecurityHeadersOptions
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import (
    hot_field,
    nested_overridable_field,
)
from app.tasks.execution.executors.nomad import NomadExecutor

MAX_LOG_RETENTION_DAYS = 365


class PreExecutionCheckMode(StrEnum):
    """Define modes for the pre-execution connectivity check.

    :cvar DISABLED: No connectivity check is performed before task dispatch.
    :vartype DISABLED: str
    :cvar WARN: Check runs before dispatch; logs a warning on failure but proceeds.
    :vartype WARN: str
    :cvar BLOCK: Check runs before dispatch; blocks dispatch on failure with an error.
    :vartype BLOCK: str
    """

    DISABLED = "disabled"
    WARN = "warn"
    BLOCK = "block"


class TasksSettings(BaseYamlAppSettings):
    """Define settings for tasks configuration.

    :cvar SETTINGS_PREFIXES: The prefixes for task-related settings in the
        configuration file.
    :vartype SETTINGS_PREFIXES: ClassVar[list[str]]
    :param UVICORN_PORT: The port to be used by Uvicorn for running the server.
        Defaults to 8002.
    :type UVICORN_PORT: int
    :param NOMAD: The Nomad executor used to integrate with Nomad. Per-leaf
        overrides are accepted via the settings API; the parent object itself
        is not patchable as a whole.
    :param DATABASE: The database configuration options. Defaults to an SQLite database
        with the name 'tasks.db'.
    :type DATABASE: DatabaseOptions
    :param SECURITY_HEADERS: Specific options for the SecurityHeadersMiddleware.
        Use ``False`` to disable the middleware completely.
    :type SECURITY_HEADERS: SecurityHeadersOptions | None
    :param SYNC_LOCK_TTL: The timeout for the TaskHistory sync lock. Must be a
        positive duration. Defaults to 5 minutes.
    :type SYNC_LOCK_TTL: timedelta
    :param PRE_EXECUTION_CONNECTIVITY_CHECK: The mode for pre-execution connectivity
        checks. Defaults to ``PreExecutionCheckMode.DISABLED``.
    :type PRE_EXECUTION_CONNECTIVITY_CHECK: PreExecutionCheckMode
    :param STALENESS_THRESHOLD_SECONDS: The maximum seconds allowed between a
        dispatch's scheduled time and its Nomad-side execution start before
        the allocation self-aborts as stale. Must be positive. Defaults to 3600.
    :type STALENESS_THRESHOLD_SECONDS: PositiveInt
    :param LOG_RETENTION_DAYS: The age in days beyond which finished task-execution
        logs (``taskhistory_log`` rows) are purged. Runtime-overridable; must be a
        positive integer no greater than 365. Defaults to 90.
    :param LOG_PURGE_BATCH_SIZE: The maximum number of ``taskhistory_log`` rows
        deleted per commit by the purge job. Runtime-overridable; must be positive.
        Defaults to 10,000.
    :param LOG_PURGE_INTERVAL: The schedule on which the log-purge periodic task
        runs. ``None`` disables seeding the task entirely. Read at startup (not
        runtime-overridable). Defaults to once per day.
    :param LOG_STREAM_CAP_BYTES: The maximum captured-log bytes retained per
        ``(task_history_id, source, stream)``. As a stream grows past the cap
        the writer drops the oldest chunks, keeping a bounded recent tail so a
        long-running execution's logs cannot grow without limit. Must be
        positive. Defaults to 104857600 (100 MiB).
    :param LOG_STREAM_EVICTION_MAX_ROWS: The maximum number of chunk rows the
        writer evicts per flush, bounding the per-append eviction work. Must be
        positive. Defaults to 1000.
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TASKS"]
    UVICORN_PORT: int = 8002
    NOMAD: NomadExecutor = nested_overridable_field(...)
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="tasks.db")
    SECURITY_HEADERS: SecurityHeadersOptions | None = nested_overridable_field(
        SecurityHeadersOptions(content_security_policy_strict=False), advanced=True
    )
    SYNC_LOCK_TTL: Annotated[timedelta, Gt(timedelta(0))] = hot_field(
        timedelta(minutes=5), advanced=True
    )
    PRE_EXECUTION_CONNECTIVITY_CHECK: PreExecutionCheckMode = hot_field(
        PreExecutionCheckMode.DISABLED
    )
    STALENESS_THRESHOLD_SECONDS: PositiveInt = hot_field(3600, advanced=True)
    LOG_RETENTION_DAYS: Annotated[int, Gt(0), Le(MAX_LOG_RETENTION_DAYS)] = hot_field(
        90, advanced=True
    )
    LOG_PURGE_BATCH_SIZE: PositiveInt = hot_field(10_000, advanced=True)
    LOG_PURGE_INTERVAL: IntervalSchedule | None = Field(
        default_factory=lambda: IntervalSchedule(every=1, period=Period.DAYS)
    )
    LOG_STREAM_CAP_BYTES: PositiveInt = hot_field(104857600, advanced=True)
    LOG_STREAM_EVICTION_MAX_ROWS: PositiveInt = hot_field(1000, advanced=True)


tasks_settings: TasksSettings = OverridableSettingsProxy(
    TasksSettings, setting_class=SettingClassEnum.TASKS_SETTINGS
)
