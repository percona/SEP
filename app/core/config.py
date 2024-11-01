"""Define the application settings."""

import logging
import re
import secrets
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import ClassVar

from kombu import Queue
from aiohttp import ClientSession
from fastapi import FastAPI
from pydantic import (
    AnyUrl,
    computed_field,
    DirectoryPath,
    HttpUrl,
    validate_call,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from pydantic_settings.sources import PathType

from app.core.auth.providers.casdoor import CasdoorSDK
from app.core.fields import (
    LogLevel,
    RelativeFilePath,
    RequiredStr,
    StrImportableAttribute,
    URL,
)
from app.core.requests import RemoteAPI
from app.core.utils import deep_dict_update

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_FASTAPI_ENV = "development"


logger = logging.getLogger(__name__)


class YamlPrefixConfigSettingsSource(YamlConfigSettingsSource):
    """Define a YAML configuration settings source with prefix handling.

    This class extends `YamlConfigSettingsSource` to allow loading settings based on
    specified prefixes. It processes the YAML data by merging data from multiple
    prefixes into a single configuration.

    :param settings_cls: The settings class associated with this source.
    :type settings_cls: type[BaseSettings]
    :param yaml_file: The path to the YAML settings file. Defaults to "settings.yaml".
    :type yaml_file: PathType | None
    :param yaml_file_encoding: The encoding of the YAML file. Defaults to `None`.
    :type yaml_file_encoding: str | None
    :param prefixes: A sequence of prefixes to navigate through the YAML data.
    :type prefixes: Sequence[RequiredStr]
    :param base_prefix: The base prefix to start the configuration. Defaults to
        "default".
    :type base_prefix: RequiredStr | None
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        yaml_file: PathType | None = Path("settings.yaml"),
        yaml_file_encoding: str | None = None,
        prefixes: Sequence[RequiredStr] = (),
        base_prefix: RequiredStr | None = "default",
    ) -> None:
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
    """Base settings class for YAML config.

    :param FASTAPI_ENV: The environment used (e.g. development, production).
        Defaults to "development".
    :type FASTAPI_ENV: str
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        yaml_file="settings.yaml",
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
            YamlPrefixConfigSettingsSource(settings_cls, prefixes=(yaml_prefix,)),
        )


class BaseYamlExtraSettings(BaseYamlSettings):
    """Base settings for extra configuration.

    :cvar SETTINGS_PREFIXES: Tuple of settings prefixes.
    :vartype SETTINGS_PREFIXES: list[str]
    :param UVICORN_HOST: The host for Uvicorn. Defaults to "127.0.0.1"
    :type UVICORN_HOST: str
    :param UVICORN_PORT: The port for Uvicorn. Defaults to 0.
    :type UVICORN_PORT: int
    :param SSL_KEYFILE: Path to the SSL key file. Defaults to None.
    :type SSL_KEYFILE: RelativeFilePath | None
    :param SSL_CERTFILE: Path to the SSL certificate file. Defaults to None.
    :type SSL_CERTFILE: RelativeFilePath | None
    """

    SETTINGS_PREFIXES: ClassVar[list[str]]
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


# TODO: Make Casdoor optional, custom auth backend model selectable in settings  # noqa: TD002, TD003
# TODO: Build our own Casdoor SDK for better methods and logging  # noqa: TD002, TD003
class CasdoorOptions(BaseModel):
    """Configuration options for Casdoor integration.

    :param ENDPOINT: The Casdoor API endpoint.
    :type ENDPOINT: StrHttpUrl
    :param CLIENT_ID: The client ID for Casdoor authentication.
    :type CLIENT_ID: str
    :param CLIENT_SECRET: The client secret for Casdoor authentication.
    :type CLIENT_SECRET: str
    :param CERTIFICATE_PATH: The file path to the Casdoor certificate.
    :type CERTIFICATE_PATH: RelativeFilePath
    :param ORGANIZATION_NAME: The name of the organization in Casdoor. Defaults to
        "built-in".
    :type ORGANIZATION_NAME: str
    :param APPLICATION_NAME: The name of the application in Casdoor. Defaults to
        "app-built-in"
    :type APPLICATION_NAME: str
    :param FRONT_ENDPOINT: The front-end endpoint for the Casdoor integration.
    :type FRONT_ENDPOINT: URL
    :param ALLOWED_ISSUERS: The allowed token issuers (iss) for JWT validation.
        Defaults to an empty list.
    :type ALLOWED_ISSUERS: list[StrHttpUrl] | Literal["*"]
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

        :param base_url: The base URL to be used when constructing the frontend
            URL. If not provided, the Casdoor API endpoint (`ENDPOINT`) is used
            as the base.
        :type base_url: URL | None
        :return: The constructed front-end URL.
        :rtype: URL
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
    def CERTIFICATE(self) -> bytes:
        """The contents of the certificate file.

        :return: The certificate file contents.
        :rtype: bytes
        """
        with self.CERTIFICATE_PATH.open("rb") as certificate_file:
            return certificate_file.read()

    @model_validator(mode="after")
    def _set_default_allowed_issuers(self) -> Self:
        if self.ALLOWED_ISSUERS != "*" and self.ENDPOINT not in self.ALLOWED_ISSUERS:
            self.ALLOWED_ISSUERS.append(self.ENDPOINT)
        return self


def route_task(
    name: str,
    args: tuple,  # noqa: ARG001
    kwargs: dict,  # noqa: ARG001
    options: dict,  # noqa: ARG001
    task: object = None,  # noqa: ARG001
    **kw: dict,  # noqa: ARG001
) -> dict:
    """Route the task to the appropriate queue based on the task name.

    :param name: The name of the task, potentially containing a queue identifier.
    :type name: str
    :param args: Positional arguments for the task (unused).
    :type args: tuple
    :param kwargs: Keyword arguments for the task (unused).
    :type kwargs: dict
    :param options: Options for the task (unused).
    :type options: dict
    :param task: The task object (optional, unused).
    :type task: object, optional
    :param kw: Additional keyword arguments (unused).
    :type kw: dict
    :return: A dictionary specifying the queue name.
    :rtype: dict
    """
    if ":" in name:
        queue, _ = name.split(":")
        return {"queue": queue}
    return {"queue": "celery"}


class CeleryConfig(BaseModel):
    """Define configuration settings for Celery."""

    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str | None = None
    CELERY_TASK_QUEUES: list = (
        # default queue
        Queue("celery"),
    )
    CELERY_TASK_ROUTES: Any = (route_task,)
    CELERY_BROKER_TRANSPORT_OPTIONS: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def handle_backend_url(cls, data: Any) -> Any:
        """Handle the backend URL and set transport options if using a filesystem broker.

        :param data: Dictionary of configuration data.
        :return: Updated dictionary of data.
        """
        if isinstance(data, dict):
            if data.get("CELERY_BROKER_URL") == "filesystem://":
                base_dir = Path(BASE_DIR)
                data["CELERY_BROKER_TRANSPORT_OPTIONS"] = {
                    "data_folder_in": base_dir / ".celery",
                    "data_folder_out": base_dir / ".celery",
                    "control_folder": base_dir / ".celery",
                }
            else:
                data["CELERY_BROKER_TRANSPORT_OPTIONS"] = {}
        return data


class Settings(BaseYamlSettings):
    """Main application settings class.

    :param CASDOOR: Casdoor configuration options.
    :type CASDOOR: CasdoorSDK
    :param AUTH_USER_MODEL: The full import path of the user model class.
        Defaults to "app.models.CasdoorUser".
    :type AUTH_USER_MODEL: StrImportableAttribute
    :param SECRET_KEY: The secret key used for signing tokens. Defaults to
        `secrets.token_urlsafe(32)`.
    :type SECRET_KEY: str
    :param LOGGING: The logging level for the application. Defaults to LogLevel.WARNING.
    :type LOGGING: LogLevel
    :param LOGGING_EXTRA: Extra log levels to set for the application.
    :type LOGGING_EXTRA: dict[str, LogLevel]
    :param BACKEND_CORS_ORIGINS: A list of allowed CORS origins.
    :type BACKEND_CORS_ORIGINS: list[AnyUrl]
    :param SSL_CAFILE: The SSL CA file to use for remote API requests.
    :type SSL_CAFILE: RelativeFilePath | None
    :param BASE_URL: The application's base URL.
    :type BASE_URL: URL | None
    """

    CASDOOR: CasdoorOptions
    CELERY: CeleryConfig
    AUTH_USER_MODEL: StrImportableAttribute = "app.models.CasdoorUser"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    LOGGING: LogLevel = LogLevel.WARNING
    LOGGING_EXTRA: dict[str, LogLevel] = {}
    BACKEND_CORS_ORIGINS: list[AnyUrl] = []
    SSL_CAFILE: RelativeFilePath | None = None
    BASE_URL: URL | None = None
    _EXTRA_CLIENT_SESSIONS: dict[tuple[str, str | None], ClientSession] = {}

    @computed_field
    @property
    def BASE_DIR(self) -> DirectoryPath:
        """The base directory for the application.

        :return: The base directory.
        :rtype: DirectoryPath
        """
        return BASE_DIR

    @validate_call
    async def get_extra_client_session(
        self,
        endpoint: HttpUrl,
        api_key: str | None = None,
        *,
        include_headers: bool = True,
    ) -> ClientSession:
        """Retrieve or create an extra client session for a given endpoint.

        Manages additional `ClientSession` instances for interacting with external APIs
        that are not created at startup. Ensures that each unique combination of
        endpoint and API key has its own session.

        :param endpoint: The base URL of the external API.
        :type endpoint: HttpUrl
        :param api_key: The API key for authentication. Defaults to None.
        :type api_key: str | None
        :param include_headers: Whether to include default headers. Defaults to True.
        :type include_headers: bool
        :return: An aiohttp `ClientSession` instance.
        :rtype: ClientSession
        :raises ClientError: If the session creation fails.
        """
        remote_api = RemoteAPI(endpoint=endpoint, api_key=api_key)
        key = (remote_api.base_url, api_key)
        if key not in self._EXTRA_CLIENT_SESSIONS:
            headers = remote_api.headers if include_headers else None
            logger.debug("Opening ClientSession for %s", remote_api.base_url)
            self._EXTRA_CLIENT_SESSIONS[key] = ClientSession(
                base_url=remote_api.base_url, headers=headers
            )
        return self._EXTRA_CLIENT_SESSIONS[key]

    async def close_extra_client_sessions(self) -> None:
        """Close all extra client sessions.

        Ensures that all additional `ClientSession` instances are properly closed
        when the application shuts down.
        """
        for (endpoint, _), client_session in self._EXTRA_CLIENT_SESSIONS.items():
            logger.debug("Closing ClientSession for %s", endpoint)
            await client_session.close()


settings = Settings()


@asynccontextmanager
async def default_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """Define the default manager for the application's lifespan.

    Ensures that the CasdoorSDK and any extra client sessions are properly managed
    during the application's startup and shutdown phases.

    :param app: The FastAPI application instance.
    :type app: FastAPI
    :yield: None
    :rtype: AsyncGenerator[None, None]
    """
    async with settings.CASDOOR:
        yield
    await settings.close_extra_client_sessions()
