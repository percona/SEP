"""Define the application settings."""

import logging
import secrets
from enum import IntEnum
from functools import cached_property
from pathlib import Path
from typing import Literal
from typing import Self

from casdoor import AsyncCasdoorSDK
from pydantic import AnyUrl
from pydantic import BaseModel
from pydantic import computed_field
from pydantic import ConfigDict
from pydantic import DirectoryPath
from pydantic import field_validator
from pydantic import model_validator
from pydantic_settings import BaseSettings
from pydantic_settings import PydanticBaseSettingsSource
from pydantic_settings import SettingsConfigDict
from pydantic_settings import YamlConfigSettingsSource
from pydantic_settings.sources import PathType

from app.core.fields import RelativeFilePath
from app.core.fields import RequiredStr
from app.core.fields import StrHttpUrl
from app.core.fields import StrImportableAttribute
from app.core.fields import URL
from app.core.utils import deep_dict_update
from app.core.utils import to_uppercase

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_FASTAPI_ENV = "development"


class BaseCaseInsensitiveModel(BaseModel):
    """A base model with case-insensitive alias generation.

    This model uses a custom alias generator that converts field names to uppercase.
    It also allows population of fields by their name, making it case-insensitive
    when handling data.
    """

    model_config = ConfigDict(alias_generator=to_uppercase, populate_by_name=True)


class YamlPrefixConfigSettingsSource(YamlConfigSettingsSource):
    def __init__(
        self,
        settings_cls: type[BaseSettings],
        yaml_file: PathType | None = Path("settings.yaml"),
        yaml_file_encoding: str | None = None,
        prefix: RequiredStr | None = None,
        base_prefix: RequiredStr | None = "default",
    ):
        super().__init__(settings_cls, yaml_file, yaml_file_encoding)
        if prefix:
            prefix_data = self.yaml_data.get(prefix, {})
            self.yaml_data = self.yaml_data.get(base_prefix, {}) if base_prefix else {}
            deep_dict_update(self.yaml_data, prefix_data)
            self.init_kwargs = self.yaml_data


class BaseYamlSettings(BaseSettings):
    """Base settings class for YAML config."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        yaml_file="settings.yaml",
        cli_parse_args=True,
        extra="ignore",
    )
    FASTAPI_ENV: str = DEFAULT_FASTAPI_ENV

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load settings from Yaml file."""
        yaml_prefix = env_settings.env_vars.get(
            "fastapi_env",
        ) or dotenv_settings.env_vars.get("fastapi_env", DEFAULT_FASTAPI_ENV)
        return (
            env_settings,
            dotenv_settings,
            YamlPrefixConfigSettingsSource(settings_cls, prefix=yaml_prefix),
        )


class BaseYamlExtraSettings(BaseYamlSettings):
    """Base settings for extra configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        yaml_file="settings.yaml",
        cli_parse_args=False,
        extra="ignore",
    )


class LogLevel(IntEnum):
    """Enumeration of logging levels."""

    CRITICAL = logging.CRITICAL
    FATAL = logging.CRITICAL
    ERROR = logging.ERROR
    WARNING = logging.WARNING
    WARN = logging.WARNING
    INFO = logging.INFO
    DEBUG = logging.DEBUG
    NOTSET = logging.NOTSET
    DISABLED = logging.NOTSET


# TODO: Make Casdoor optional, custom auth backend model selectable in settings
class CasdoorOptions(BaseModel):
    """Configuration options for Casdoor integration.

    Attributes
    ----------
    ENDPOINT : str
        The Casdoor API endpoint.
    CLIENT_ID : str
        The client ID for Casdoor authentication.
    CLIENT_SECRET : str
        The client secret for Casdoor authentication.
    CERTIFICATE_PATH : FilePath
        The file path to the Casdoor certificate. Defaults to "data/token_jwt_key.pem".
    ORGANIZATION_NAME : str
        The name of the organization in Casdoor. Defaults to "built-in".
    APPLICATION_NAME : str
        The name of the application in Casdoor. Defaults to "app-built-in".
    FRONT_ENDPOINT : str, optional
        The front-end endpoint for the Casdoor integration.
    CERTIFICATE
    SDK

    """

    ENDPOINT: StrHttpUrl
    CLIENT_ID: str
    CLIENT_SECRET: str
    CERTIFICATE_PATH: RelativeFilePath
    ORGANIZATION_NAME: str = "built-in"
    APPLICATION_NAME: str = "app-built-in"
    FRONT_ENDPOINT: URL = URL()
    ALLOWED_ISSUERS: list[StrHttpUrl] | Literal["*"] = []

    def get_frontend_url(self, base_url: URL | None = None) -> URL:
        frontend_url = self.FRONT_ENDPOINT
        base_url = URL(self.ENDPOINT) if base_url is None else base_url
        url_data = {
            "scheme": frontend_url.scheme or base_url.scheme,
            "hostname": frontend_url.hostname or base_url.hostname,
            "port": frontend_url.port or base_url.port,
            "path": frontend_url.path or base_url.path,
        }
        return frontend_url.replace(**url_data)

    @computed_field
    @cached_property
    def CERTIFICATE(self) -> str:
        """The contents of the certificate file."""
        with self.CERTIFICATE_PATH.open() as certificate_file:
            return certificate_file.read()

    @cached_property
    def SDK(self) -> AsyncCasdoorSDK:
        """Asynchronous Casdoor SDK instance."""
        return AsyncCasdoorSDK(
            endpoint=self.ENDPOINT,
            client_id=self.CLIENT_ID,
            client_secret=self.CLIENT_SECRET,
            certificate=self.CERTIFICATE,
            org_name=self.ORGANIZATION_NAME,
            application_name=self.APPLICATION_NAME,
        )

    @model_validator(mode="after")
    def _set_default_allowed_issuers(self) -> Self:
        if self.ALLOWED_ISSUERS != "*" and self.ENDPOINT not in self.ALLOWED_ISSUERS:
            self.ALLOWED_ISSUERS.append(self.ENDPOINT)
        return self


class Settings(BaseYamlSettings):
    """Main application settings class.

    Attributes
    ----------
    CASDOOR : CasdoorOptions
        Casdoor configuration options.
    AUTH_USER_MODEL : StrImportableAttribute, optional
        The full import path of the user model class. Must be importable.
    JWT_ALGORITHM : str, optional
        The JWT algorithm used for encoding/decoding tokens, either "HS256" or "RS256".
        Defaults to "RS256".
    SECRET_KEY : str, optional
        The secret key used for signing tokens.
        Defaults to the contents of PRIVATE_KEY_PATH.
    PRIVATE_KEY_PATH : FilePath, optional
        The file path to the private key used for signing tokens.
    LOGGING : LogLevel, optional
        The logging level for the application. Defaults to `LogLevel.WARNING`.
    BACKEND_CORS_ORIGINS : list of AnyUrl
        A list of allowed CORS origins.
    PUBLIC_KEY

    """

    CASDOOR: CasdoorOptions
    AUTH_USER_MODEL: StrImportableAttribute = ""
    JWT_ALGORITHM: Literal["HS256", "RS256"] = "HS256"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    PRIVATE_KEY_PATH: RelativeFilePath | None = None
    LOGGING: LogLevel = LogLevel.WARNING
    BACKEND_CORS_ORIGINS: list[AnyUrl] = []
    SSL_CAFILE: RelativeFilePath | None = None

    @computed_field
    @property
    def BASE_DIR(self) -> DirectoryPath:
        """The base directory for the application."""
        return BASE_DIR

    @computed_field
    @property
    def PUBLIC_KEY(self) -> str:
        """The public key used for decoding JWT tokens."""
        if self.JWT_ALGORITHM == "RS256":
            return self.CASDOOR.CERTIFICATE
        return self.SECRET_KEY

    @model_validator(mode="after")
    def _set_default_secret_key(self) -> Self:
        if self.PRIVATE_KEY_PATH:
            # TODO: private key with passphrase
            with self.PRIVATE_KEY_PATH.open() as key_file:
                self.SECRET_KEY = key_file.read()
        return self

    @field_validator("LOGGING", mode="before")
    @classmethod
    def validate_log_level(cls, v: LogLevel | str) -> LogLevel:
        """Uppercase the provided logging level."""
        if isinstance(v, LogLevel):
            return v
        try:
            return LogLevel[v.upper()]
        except KeyError as exc:
            raise ValueError(f"Invalid log level: '{v}'") from exc


settings = Settings()
