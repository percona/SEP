"""Define settings for the Inventory API."""

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
    NOMAD: NomadOptions
    EXECUTE_MODE: str = "background"
    TASKS_ENDPOINT: HttpUrl
    TASKS_SSL_KEYFILE: RelativeFilePath | None = None
    TASKS_SSL_CERTFILE: RelativeFilePath | None = None


tasks_settings = TasksSettings()
