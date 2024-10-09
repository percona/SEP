"""Define settings for the Inventory API."""

from typing import ClassVar

from pydantic import ConfigDict

from app.core.config import BaseYamlExtraSettings
from app.core.db.config import DatabaseOptions
from app.tasks.nomad import NomadExecutor


class TasksSettings(BaseYamlExtraSettings):
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
    """

    model_config = ConfigDict(extra="allow")
    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TASKS"]
    UVICORN_PORT: int = 8002
    NOMAD: NomadExecutor
    EXECUTE_MODE: str = "background"
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="tasks.db")


tasks_settings = TasksSettings()
