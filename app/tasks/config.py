"""Define settings for the Inventory API."""

from typing import ClassVar

from pydantic import BaseModel
from pydantic import HttpUrl

from app.core.config import BaseYamlExtraSettings
from app.core.fields import RelativeFilePath


class NomadOptions(BaseModel):
    ENDPOINT: HttpUrl
    SECURE: bool = False
    TIMEOUT: int = 10
    VERIFY: bool | RelativeFilePath = False
    CERT: tuple[RelativeFilePath, RelativeFilePath] | RelativeFilePath = ()


class TasksSettings(BaseYamlExtraSettings):
    SETTINGS_PREFIXES: ClassVar[tuple[str]] = ("TASKS",)
    UVICORN_PORT: int = 8002
    NOMAD: NomadOptions
    EXECUTE_MODE: str = "background"


tasks_settings = TasksSettings()
