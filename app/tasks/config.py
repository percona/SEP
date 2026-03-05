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
from typing import ClassVar

from app.core.config import BaseYamlAppSettings
from app.core.db.config import DatabaseOptions
from app.core.middleware.security_headers import SecurityHeadersOptions
from app.tasks.execution.executors.nomad import NomadExecutor


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
        Use `False` to disable the middleware completely.
    :type SECURITY_HEADERS: SecurityHeadersOptions | None
    :param SYNC_LOCK_TTL: The timeout for the TaskHistory sync lock. Defaults to 5
        minutes.
    :type SYNC_LOCK_TTL: timedelta
    :param INVENTORY_SYNC_API_KEY: The PMM API key used for scheduled inventory sync
        execution. Defaults to None, meaning scheduled sync is not configured.
    :type INVENTORY_SYNC_API_KEY: str | None
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TASKS"]
    UVICORN_PORT: int = 8002
    NOMAD: NomadExecutor
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="tasks.db")
    SECURITY_HEADERS: SecurityHeadersOptions | None = SecurityHeadersOptions(
        content_security_policy_strict=False
    )
    SYNC_LOCK_TTL: timedelta = timedelta(minutes=5)
    INVENTORY_SYNC_API_KEY: str | None = None


tasks_settings = TasksSettings()
