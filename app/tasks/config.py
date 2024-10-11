"""Define settings for the Inventory API."""

from typing import ClassVar

from pydantic import BaseModel
from pydantic import HttpUrl

from app.core.config import BaseYamlExtraSettings
from app.core.db.config import DatabaseOptions
from app.core.fields import RelativeFilePath


class NomadOptions(BaseModel):
    """Define settings for Nomad integration.

    Attributes
    ----------
    ENDPOINT : HttpUrl
        The URL for the Nomad API endpoint.
    SECURE : bool
        Whether to use a secure connection. Defaults to False.
    TIMEOUT : int
        The timeout in seconds for requests to the Nomad API. Defaults to 10 seconds.
    VERIFY : bool or RelativeFilePath
        Whether to verify SSL certificates. Can be a file path to the SSL certificate.
        Defaults to False.
    CERT : tuple[RelativeFilePath, RelativeFilePath] or RelativeFilePath
        SSL certificate and key paths, or a single certificate file path.
        Defaults to an empty tuple.

    """

    ENDPOINT: HttpUrl
    SECURE: bool = False
    TIMEOUT: int = 10
    VERIFY: bool | RelativeFilePath = False
    CERT: tuple[RelativeFilePath, RelativeFilePath] | RelativeFilePath = ()


class TasksSettings(BaseYamlExtraSettings):
    """Define settings for tasks configuration.

    Attributes
    ----------
    SETTINGS_PREFIXES : ClassVar[tuple[str]]
        The prefixes for task-related settings in the configuration file.
    UVICORN_PORT : int
        The port to be used by Uvicorn for running the server. Defaults to 8002.
    NOMAD : NomadOptions
        The configuration options for integrating with Nomad.
    EXECUTE_MODE : str
        The execution mode for tasks. Defaults to 'background'.
    DATABASE : DatabaseOptions
        The database configuration options.
        Defaults to an SQLite database with the name 'tasks.db'.

    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TASKS"]
    UVICORN_PORT: int = 8002
    NOMAD: NomadOptions
    EXECUTE_MODE: str = "background"
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="tasks.db")


tasks_settings = TasksSettings()
