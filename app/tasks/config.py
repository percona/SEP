"""Define settings for the Tasks app."""

from typing import ClassVar, Union

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
    :param EXECUTE_MODE: The execution mode for tasks. Defaults to 'background'.
    :type EXECUTE_MODE: str
    :param DATABASE: The database configuration options. Defaults to an SQLite database
        with the name 'tasks.db'.
    :type DATABASE: DatabaseOptions
    :param SECURITY_HEADERS: Specific options for the SecurityHeadersMiddleware.
        Use `False` to disable the middleware completely.
    :type SECURITY_HEADERS: SecurityHeadersOptions | None
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TASKS"]
    UVICORN_PORT: int = 8002
    NOMAD: NomadExecutor
    EXECUTE_MODE: str = "background"
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="tasks.db")
    SECURITY_HEADERS: SecurityHeadersOptions | None = SecurityHeadersOptions(
        content_security_policy_strict=False
    )
    LOG_ANON: bool | list[str] = True


tasks_settings = TasksSettings()
