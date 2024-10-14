"""Define settings for the Inventory API."""

from typing import ClassVar

from pydantic import BaseModel
from pydantic import HttpUrl

from app.core.config import BaseYamlExtraSettings
from app.core.db.config import DatabaseOptions
from app.core.fields import RelativeFilePath


class NomadOptions(BaseModel):
    """Define settings for Nomad integration.

    :param ENDPOINT: The URL for the Nomad API endpoint.
    :type ENDPOINT: HttpUrl
    :param SECURE: Whether to use a secure connection. Defaults to False.
    :type SECURE: bool
    :param TIMEOUT: The timeout in seconds for requests to the Nomad API. Defaults to
        10 seconds.
    :type TIMEOUT: int
    :param VERIFY: Whether to verify SSL certificates. Can be a file path to the SSL
        certificate. Defaults to False.
    :type VERIFY: bool | RelativeFilePath
    :param CERT: SSL certificate and key paths, or a single certificate file path.
        Defaults to an empty tuple.
    :type CERT: tuple[RelativeFilePath, RelativeFilePath] | RelativeFilePath
    """

    ENDPOINT: HttpUrl
    SECURE: bool = False
    TIMEOUT: int = 10
    VERIFY: bool | RelativeFilePath = False
    CERT: tuple[RelativeFilePath, RelativeFilePath] | RelativeFilePath = ()


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

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TASKS"]
    UVICORN_PORT: int = 8002
    NOMAD: NomadOptions
    EXECUTE_MODE: str = "background"
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="tasks.db")


tasks_settings = TasksSettings()
