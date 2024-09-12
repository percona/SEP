"""Define the application settings."""

import logging
import re
import secrets
from enum import IntEnum
from functools import cached_property
from pathlib import Path
from typing import ClassVar
from typing import Literal
from typing import Self
from typing import Sequence

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
        prefixes: Sequence[RequiredStr] = (),
        base_prefix: RequiredStr | None = "default",
    ):
        super().__init__(settings_cls, yaml_file, yaml_file_encoding)
        if prefixes:
            prefix_data = self.yaml_data.get(prefixes[0], {})
            base_prefix_data = (
                self.yaml_data.get(base_prefix, {}) if base_prefix else {}
            )
            for prefix in prefixes[1:]:
                prefix_data = prefix_data.get(prefix, {})
                base_prefix_data = (
                    base_prefix_data.get(prefix, {}) if base_prefix else {}
                )
            self.yaml_data = base_prefix_data
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
    LOGGING: LogLevel = LogLevel.WARNING

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
            YamlPrefixConfigSettingsSource(settings_cls, prefixes=(yaml_prefix,)),
        )

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


class BaseYamlExtraSettings(BaseYamlSettings):
    """Base settings for extra configuration."""

    SETTINGS_PREFIXES: ClassVar[tuple[str]]
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        yaml_file="settings.yaml",
        cli_parse_args=False,
        extra="ignore",
    )
    UVICORN_HOST: str = "127.0.0.1"
    UVICORN_PORT: int = 0
    SSL_KEYFILE: RelativeFilePath | None = None
    SSL_CERTFILE: RelativeFilePath | None = None

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
        env_prefix = "__".join(cls.SETTINGS_PREFIXES).lower()
        for env_source in [env_settings, dotenv_settings]:
            env_vars = {}
            for key, value in env_source.env_vars.items():
                env_vars[re.sub(f"^{env_prefix}__([a-zA-Z0-9_-]+)$", r"\1", key)] = (
                    value
                )
            env_source.env_vars = env_vars
        return (
            env_settings,
            dotenv_settings,
            YamlPrefixConfigSettingsSource(
                settings_cls,
                prefixes=(yaml_prefix, *cls.SETTINGS_PREFIXES),
            ),
        )


# TODO: Make Casdoor optional, custom auth backend model selectable in settings
# TODO: Build our own Casdoor SDK for better methods and logging
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
    ALLOWED_ISSUERS : Literal["*"] or list of StrHttpUrl, optional
        The allowed token issuers (iss) for JWT validation. Use "*" to allow any issuer.
        Defaults to a list with `ENDPOINT`.
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
        """Get Casdoor's front-end URL from a base URL.

        Construct the frontend URL for Casdoor integration by replacing any missing
         parts (scheme, hostname, port, path) from the `FRONT_ENDPOINT` with
         corresponding parts from the `base_url`.

        Parameters
        ----------
        base_url : URL, optional
            The base URL to be used when constructing the frontend URL. If not provided,
            the Casdoor API endpoint (`ENDPOINT`) is used as the base.

        Returns
        -------
        URL
            The constructed front-end URL.

        """
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
    SECRET_KEY : str, optional
        The secret key used for signing tokens.
        Defaults to `secrets.token_urlsafe(32)`.
    LOGGING : LogLevel, optional
        The logging level for the application. Defaults to `LogLevel.WARNING`.
    BACKEND_CORS_ORIGINS : list of AnyUrl
        A list of allowed CORS origins.
    SSL_CAFILE: RelativeFilePath, optional
        The SSL CA file to use for remote API requests.
    BASE_DIR

    """

    CASDOOR: CasdoorOptions
    AUTH_USER_MODEL: StrImportableAttribute = ""
    SECRET_KEY: str = secrets.token_urlsafe(32)
    LOGGING: LogLevel = LogLevel.WARNING
    BACKEND_CORS_ORIGINS: list[AnyUrl] = []
    SSL_CAFILE: RelativeFilePath | None = None

    @computed_field
    @property
    def BASE_DIR(self) -> DirectoryPath:
        """The base directory for the application."""
        return BASE_DIR


settings = Settings()
