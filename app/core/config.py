"""Define the application settings."""

import logging.config
import re
import secrets
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, ClassVar, Literal, Self

from aiohttp import ClientSession
from fastapi import APIRouter, FastAPI
from fastapi.applications import AppType
from fastapi.middleware.cors import CORSMiddleware
from pydantic import (
    computed_field,
    DirectoryPath,
    Field,
    field_validator,
    HttpUrl,
    model_validator,
    validate_call,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from pydantic_settings.sources import DotEnvSettingsSource, EnvSettingsSource, PathType
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import Lifespan

from app import BASE_DIR
from app.core.auth.providers.casdoor import CasdoorSDK
from app.core.celery.config import CeleryOptions
from app.core.middleware.security_headers import (
    SecurityHeadersMiddleware,
    SecurityHeadersOptions,
)
from app.core.requests import RemoteAPI
from app.core.utils import deep_dict_update, json_serializer
from app.core.utils.fields import (
    LogLevel,
    RelativeFilePath,
    RequiredStr,
    StrHttpUrl,
    StrImportableAttribute,
    URL,
)

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(name)s: %(message)s <%(process)d>",
        },
        "uvicorn": {
            "format": "uvicorn: %(message)s <%(process)d>",
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "rich.logging.RichHandler",
            "omit_repeated_times": False,
            "show_path": False,
        },
        "app": {
            "formatter": "default",
            "class": "rich.logging.RichHandler",
            "omit_repeated_times": False,
            "show_path": True,
        },
        "uvicorn": {
            "formatter": "uvicorn",
            "class": "rich.logging.RichHandler",
            "omit_repeated_times": False,
            "show_path": False,
        },
        "celery": {
            "formatter": "default",
            "class": "rich.logging.RichHandler",
            "omit_repeated_times": False,
            "show_path": False,
        },
    },
    "loggers": {
        "": {"handlers": ["default"], "level": "INFO"},
        "app": {"handlers": ["app"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["celery"], "level": "INFO", "propagate": False},
        "celery.beat": {"handlers": ["celery"], "level": "INFO", "propagate": False},
        "sqlalchemy_celery_beat": {
            "handlers": ["celery"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn": {"handlers": ["uvicorn"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["uvicorn"], "level": "INFO", "propagate": False},
        "uvicorn.access": {
            "handlers": ["uvicorn"],
            "level": "INFO",
            "propagate": False,
        },
    },
}


class PreEnvSettings(BaseSettings):
    """Define meta environment settings read that need to be read before the others.

    :param FASTAPI_ENV: The environment used (e.g. development, production).
        Defaults to "development".
    :type FASTAPI_ENV: str
    :param ENV_FILE: The dot env file used to populate the applications settings.
        Defaults to ".env" in the current directory.
    :type ENV_FILE: Path
    :param SETTINGS_FILE: The YAML file used to populate the applications settings.
        Defaults to "settings.yaml" in the current directory.
    :type SETTINGS_FILE: Path
    """

    model_config = SettingsConfigDict(extra="ignore")
    FASTAPI_ENV: str = "development"
    ENV_FILE: Path = Path(".env")
    SETTINGS_FILE: Path = Path("settings.yaml")


pre_env_settings = PreEnvSettings()


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
        yaml_file: PathType | None = pre_env_settings.SETTINGS_FILE,
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

    :cvar SETTINGS_PREFIXES: Tuple of settings prefixes.
    :vartype SETTINGS_PREFIXES: list[str]
    :param FASTAPI_ENV: The environment used (e.g. development, production).
        Defaults to "development".
    :type FASTAPI_ENV: str
    """

    model_config = SettingsConfigDict(
        env_file=pre_env_settings.ENV_FILE,
        env_nested_delimiter="__",
        yaml_file=pre_env_settings.SETTINGS_FILE,
        extra="ignore",
    )
    SETTINGS_PREFIXES: ClassVar[list[str]] = []
    FASTAPI_ENV: str = pre_env_settings.FASTAPI_ENV

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: EnvSettingsSource,
        dotenv_settings: DotEnvSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Load settings from Yaml file."""
        yaml_prefix = env_settings.env_vars.get(
            "fastapi_env",
        ) or dotenv_settings.env_vars.get("fastapi_env", pre_env_settings.FASTAPI_ENV)
        if cls.SETTINGS_PREFIXES:
            env_prefix = "__".join(cls.SETTINGS_PREFIXES).lower()
            for env_source in [env_settings, dotenv_settings]:
                env_vars = {}
                for key, value in env_source.env_vars.items():
                    env_vars[
                        re.sub(f"^{env_prefix}__([a-zA-Z0-9_-]+)$", r"\1", key)
                    ] = value
                env_source.env_vars = env_vars
        return (
            env_settings,
            dotenv_settings,
            YamlPrefixConfigSettingsSource(
                settings_cls,
                prefixes=(yaml_prefix, *cls.SETTINGS_PREFIXES),
            ),
        )


class Settings(BaseYamlSettings):
    """Main application settings class.

    :param CASDOOR: Casdoor configuration options.
    :type CASDOOR: CasdoorSDK
    :param CELERY: Celery configuration options.
    :type CELERY: CeleryOptions
    :param AUTH_USER_MODEL: The full import path of the user model class.
        Defaults to "app.models.CasdoorUser".
    :type AUTH_USER_MODEL: StrImportableAttribute
    :param ALLOW_CONCURRENT_SESSIONS: Whether to allow concurrent sessions for the same
        user. Defaults to False, meaning all previous sessions will be invalidated once
        a new one is created.
    :type ALLOW_CONCURRENT_SESSIONS: bool
    :param SECRET_KEY: The secret key used for signing tokens. Defaults to
        `secrets.token_urlsafe(32)`.
    :type SECRET_KEY: str
    :param LOGGING: The logging level for the application. Defaults to LogLevel.WARNING.
    :type LOGGING: LogLevel
    :param LOGGING_CONFIG: dictConfig logging configuration.
    :type LOGGING_CONFIG: dict[str, Any]
    :param SSL_CAFILE: The SSL CA file to use for remote API requests.
    :type SSL_CAFILE: RelativeFilePath | None
    :param BASE_URL: The application's base URL.
    :type BASE_URL: URL | None
    :param BACKEND_CORS_ORIGINS: A global list of allowed CORS origins, to be used as
        the default BACKEND_CORS_ORIGINS setting across all apps.
    :type BACKEND_CORS_ORIGINS: list[StrHttpUrl] | None
    :param ALLOWED_HOSTS: A global list of trusted domain names or wildcards, to be used
        as the default ALLOWED_HOSTS setting across all apps.
    :type ALLOWED_HOSTS: list[str]
    :param SECURITY_HEADERS: Global options for the SecurityHeadersMiddleware, to be
        used as the default SECURITY_HEADERS setting across all apps.
    :type SECURITY_HEADERS: SecurityHeadersOptions | None
    """

    CASDOOR: CasdoorSDK
    CELERY: CeleryOptions
    AUTH_USER_MODEL: StrImportableAttribute = "app.models.CasdoorUser"
    ALLOW_CONCURRENT_SESSIONS: bool = False
    SECRET_KEY: str = secrets.token_urlsafe(32)
    LOGGING: LogLevel = LogLevel.WARNING
    LOGGING_CONFIG: dict[str, Any] = {}
    SSL_CAFILE: RelativeFilePath | None = None
    BASE_URL: URL | None = None
    BACKEND_CORS_ORIGINS: list[StrHttpUrl] | None = None
    ALLOWED_HOSTS: list[str] = []
    SECURITY_HEADERS: SecurityHeadersOptions | None = SecurityHeadersOptions()
    _EXTRA_CLIENT_SESSIONS: dict[tuple[str, str | None], ClientSession] = {}

    @computed_field
    @property
    def BASE_DIR(self) -> DirectoryPath:
        """The base directory for the application.

        :return: The base directory.
        :rtype: DirectoryPath
        """
        return BASE_DIR

    @field_validator("LOGGING_CONFIG")
    @classmethod
    def _set_default_logging_config(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Return the default configuration updated with the provided data.

        :param v: The new logging configuration.
        :type v: dict[str, Any]
        :return: The updated configuration.
        :rtype: dict[str, Any]
        """
        logging_config = deepcopy(LOGGING_CONFIG)
        deep_dict_update(logging_config, v)
        return logging_config

    @model_validator(mode="after")
    def set_log_level(self) -> Self:
        """Set the logging level for the application.

        Set the default log level in `self.LOGGING_CONFIG` according to the `LOGGING`
        setting.

        :return: Validated settings with default logging level set.
        :rtype: Settings
        """
        self.LOGGING_CONFIG["loggers"][""]["level"] = self.LOGGING
        self.LOGGING_CONFIG["loggers"]["app"]["level"] = self.LOGGING
        return self

    @validate_call
    def get_extra_client_session(
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
                base_url=remote_api.base_url,
                headers=headers,
                json_serialize=json_serializer,
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
logging.config.dictConfig(settings.LOGGING_CONFIG)
logger = logging.getLogger(__name__)


class BaseYamlAppSettings(BaseYamlSettings):
    """Define base settings for a FastAPI app.

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
    :param BACKEND_CORS_ORIGINS: A list of allowed CORS origins. Use None to disable the
        CORSMiddleware.
    :type BACKEND_CORS_ORIGINS: list[StrHttpUrl] | None
    :param ALLOWED_HOSTS: A list of trusted domain names or wildcards, to which all
        incoming requests have the Host header validated against. Use `["*"]` to allow
        any hostname. Defaults to `settings.ALLOWED_HOSTS`.
    :type ALLOWED_HOSTS: list[str]
    :param SECURITY_HEADERS: Specific options for the SecurityHeadersMiddleware.
        Use `False` to disable the middleware completely.
    :type SECURITY_HEADERS: SecurityHeadersOptions | None
    """

    UVICORN_HOST: str = "127.0.0.1"
    UVICORN_PORT: int = 0
    SSL_KEYFILE: RelativeFilePath | None = None
    SSL_CERTFILE: RelativeFilePath | None = None
    BACKEND_CORS_ORIGINS: list[StrHttpUrl] | None = settings.BACKEND_CORS_ORIGINS
    ALLOWED_HOSTS: list[str] = Field(settings.ALLOWED_HOSTS, min_length=1)
    SECURITY_HEADERS: SecurityHeadersOptions | None = SecurityHeadersOptions()

    @field_validator("ALLOWED_HOSTS")
    @classmethod
    def _warn_allowed_hosts_match_any(cls, v: list[str]) -> list[str]:
        if "*" in v:
            logger.warning(
                "The value '*' in %s.ALLOWED_HOSTS matches any hostname "
                "- use it carefully",
                cls.__name__,
            )
        return v

    @field_validator("SECURITY_HEADERS")
    @classmethod
    def _warn_security_headers_middleware_enabled_without_headers(
        cls, v: SecurityHeadersOptions | Literal[False]
    ) -> SecurityHeadersOptions | Literal[False]:
        if v and not any(v.model_dump().values()):
            logger.warning(
                "SecurityHeadersMiddleware is enabled in %s but all options are "
                "disabled. Set `SECURITY_HEADERS` to False to disable the middleware.",
                cls.__name__,
            )
        return v


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


def create_app(
    *routers: APIRouter,
    lifespan: Lifespan[AppType] | None = None,
    backend_cors_origins: list[StrHttpUrl] | None = None,
    allowed_hosts: list[str] | None = None,
    security_headers: SecurityHeadersOptions | None = None,
) -> FastAPI:
    """Create and configure the FastAPI app.

    :param routers: Routers to include to created app.
    :type routers: APIRouter
    :param lifespan: Lifespan context manager for the FastAPI app, if any. Defaults to
        None.
    :type lifespan: Lifespan[AppType] | None
    :param backend_cors_origins: A list of allowed origins for the CORSMiddleware.
        Defaults to None, meaning the middleware won't be added to the app.
    :type backend_cors_origins: list[StrHttpUrl] | None
    :param allowed_hosts: List of allowed hosts for the TrustedHostMiddleware. Defaults
        to None, meaning the middleware won't be added to the app.
    :type allowed_hosts: list[str]
    :param security_headers: Options for the SecurityHeadersMiddleware. Defaults to
        None, meaning the middleware won't be added to the app.
    :return: An instance of the FastAPI application with an attached Celery app.
    :rtype: FastAPI
    """
    app = FastAPI(lifespan=lifespan)
    if backend_cors_origins is not None:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=backend_cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    if allowed_hosts is not None:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    if security_headers is not None:
        app.add_middleware(SecurityHeadersMiddleware, options=security_headers)
    for router in routers:
        app.include_router(router)
    return app
