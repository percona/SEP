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

from pydantic import AfterValidator, PositiveInt

from app.core.config import BaseYamlAppSettings
from app.core.db.config import DatabaseOptions
from app.core.middleware.security_headers import SecurityHeadersOptions
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import (
    hot_field,
    materialize_fingerprint,
    nested_overridable_field,
)
from app.tasks.execution.executors.nomad import NomadExecutor


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


def _require_positive_ttl(value: timedelta) -> timedelta:
    """Reject a non-positive ``SYNC_LOCK_TTL`` on both YAML and override paths.

    A zero or negative TTL puts the sync-lock cutoff ``utc_now() -
    SYNC_LOCK_TTL`` at or after the present, so every ``RUNNING`` row is always
    claimable and the lock is effectively disabled. As an ``AfterValidator`` on
    the annotation the guard runs on both the YAML-load path and the override
    coercion path, which a model ``@field_validator`` would not.

    :param value: The candidate sync-lock TTL.
    :return: ``value`` unchanged when it is a positive duration.
    :raises ValueError: When ``value`` is zero or negative.
    """
    if value <= timedelta(0):
        raise ValueError("SYNC_LOCK_TTL must be a positive duration")
    return value


class TasksSettings(BaseYamlAppSettings):
    """Define settings for tasks configuration.

    :cvar SETTINGS_PREFIXES: The prefixes for task-related settings in the
        configuration file.
    :vartype SETTINGS_PREFIXES: ClassVar[list[str]]
    :param UVICORN_PORT: The port to be used by Uvicorn for running the server.
        Defaults to 8002.
    :type UVICORN_PORT: int
    :param NOMAD: The configuration options for integrating with Nomad.
    :type NOMAD: NomadOptions
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
        checks. Defaults to ``PreExecutionCheckMode.WARN``.
    :type PRE_EXECUTION_CONNECTIVITY_CHECK: PreExecutionCheckMode
    :param STALENESS_THRESHOLD_SECONDS: The maximum seconds allowed between a
        dispatch's scheduled time and its Nomad-side execution start before
        the allocation self-aborts as stale. Must be positive. Defaults to 3600.
    :type STALENESS_THRESHOLD_SECONDS: PositiveInt
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TASKS"]
    UVICORN_PORT: int = 8002
    NOMAD: NomadExecutor = hot_field(..., materializer=materialize_fingerprint)
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="tasks.db")
    SECURITY_HEADERS: SecurityHeadersOptions | None = nested_overridable_field(
        SecurityHeadersOptions(content_security_policy_strict=False), advanced=True
    )
    SYNC_LOCK_TTL: Annotated[timedelta, AfterValidator(_require_positive_ttl)] = (
        hot_field(timedelta(minutes=5))
    )
    PRE_EXECUTION_CONNECTIVITY_CHECK: PreExecutionCheckMode = hot_field(
        PreExecutionCheckMode.WARN
    )
    STALENESS_THRESHOLD_SECONDS: PositiveInt = hot_field(3600)


tasks_settings: TasksSettings = OverridableSettingsProxy(
    TasksSettings, setting_class=SettingClassEnum.TASKS_SETTINGS
)
