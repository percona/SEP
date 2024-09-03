"""Define settings for the Inventory API."""

from pydantic import BaseModel
from pydantic import HttpUrl

from app.core.config import BaseYamlExtraSettings


class NomadOptions(BaseModel):
    ENDPOINT: HttpUrl
    SECURE: bool = False
    TIMEOUT: int = 10
    VERIFY: bool = False


class TasksSettings(BaseYamlExtraSettings):
    NOMAD: NomadOptions
    EXECUTE_MODE: str = "background"
    TASKS_ENDPOINT: HttpUrl


tasks_settings = TasksSettings()
