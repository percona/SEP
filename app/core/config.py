# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define the application settings."""

import hashlib
import hmac
import logging.config
import re
import secrets
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from functools import cached_property
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal, Self, TypeVar
from urllib.parse import urlparse

from fastapi import APIRouter, FastAPI
from fastapi.applications import AppType
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from pydantic import (
    computed_field,
    DirectoryPath,
    Field,
    field_validator,
    model_validator,
    PositiveInt,
    SecretStr,
    StringConstraints,
    validate_call,
)
from pydantic_settings import (
    BaseSettings,
    NestedSecretsSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from pydantic_settings.sources import DotEnvSettingsSource, EnvSettingsSource, PathType
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import Lifespan

from app import BASE_DIR
from app.core.celery.config import CeleryOptions
from app.core.middleware.security_headers import (
    SecurityHeadersMiddleware,
    SecurityHeadersOptions,
)
from app.core.models import BaseLowercaseModel
from app.core.requests import BaseRemoteAPI, ClientRegistry, RemoteAPI
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import hot_field, not_overridable_field
from app.core.utils import deep_dict_update
from app.core.utils.fields import (
    EmptyStrToNone,
    LogLevel,
    NonEmptyStr,
    redact_credential_url,
    RelativeFilePathField,
    StrCredentialHttpUrl,
    StrHttpUrl,
    TimedeltaSeconds,
    URL,
)
from app.core.utils.openapi import (
    generate_tag_prefixed_unique_id,
    install_namespaced_openapi,
)


def _sanitize_client_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of remote-API client kwargs safe to log.

    Any value carrying an embedded URL password (e.g. ``endpoint``) is
    redacted so credentials never reach the debug log. ``SecretStr`` values
    already mask themselves on ``repr`` and are left untouched.

    :param kwargs: The client construction kwargs about to be logged.
    :type kwargs: dict[str, Any]
    :return: A copy with credential URLs redacted.
    :rtype: dict[str, Any]
    """
    safe: dict[str, Any] = {}
    for key, value in kwargs.items():
        raw = str(value)
        redacted = redact_credential_url(raw)
        safe[key] = redacted if redacted != raw else value
    return safe


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "context": {
            "()": "app.core.log.ContextFilter",
        },
    },
    "formatters": {
        "default": {
            "()": "app.core.log.ContextFormatter",
            "fmt": "%(name)s: [%(correlation_id)s] %(message)s <%(process)d>",
            "skip_keys": ["correlation_id"],
        },
        "uvicorn": {
            "()": "app.core.log.ContextFormatter",
            "fmt": "uvicorn: [%(correlation_id)s] %(message)s <%(process)d>",
            "skip_keys": ["correlation_id"],
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "rich.logging.RichHandler",
            "filters": ["context"],
            "omit_repeated_times": False,
            "show_path": False,
        },
        "app": {
            "formatter": "default",
            "class": "rich.logging.RichHandler",
            "filters": ["context"],
            "omit_repeated_times": False,
            "show_path": True,
        },
        "uvicorn": {
            "formatter": "uvicorn",
            "class": "rich.logging.RichHandler",
            "filters": ["context"],
            "omit_repeated_times": False,
            "show_path": False,
        },
        "celery": {
            "formatter": "default",
            "class": "rich.logging.RichHandler",
            "filters": ["context"],
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
        "watchfiles.main": {"handlers": ["default"], "level": "WARNING"},
    },
}


class PreEnvSettings(BaseSettings):
    """Define meta environment settings read that need to be read before the others.

    :param FASTAPI_ENV: The environment used (e.g. development, production).
        Defaults to "development".
    :param ENV_FILE: The dot env file used to populate the applications settings.
        Defaults to ".env" in the current directory.
    :param SETTINGS_FILE: The YAML file used to populate the applications settings.
        Defaults to "settings.yaml" in the current directory.
    :param SECRETS_DIR: The directory holding mounted secret files, each named after
        the canonical ``__``-nested variable it supplies. Defaults to unset, in which
        case no secret files are read.
    """

    model_config = SettingsConfigDict(extra="ignore")
    FASTAPI_ENV: str = "development"
    ENV_FILE: Path = Path(".env")
    SETTINGS_FILE: Path = Path("settings.yaml")
    SECRETS_DIR: Path | EmptyStrToNone = None


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
    :type prefixes: Sequence[NonEmptyStr]
    :param base_prefix: The base prefix to start the configuration. Defaults to
        "default".
    :type base_prefix: NonEmptyStr | None
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        yaml_file: PathType | None = pre_env_settings.SETTINGS_FILE,
        yaml_file_encoding: str | None = None,
        prefixes: Sequence[NonEmptyStr] = (),
        base_prefix: NonEmptyStr | None = "default",
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
        secrets_dir=pre_env_settings.SECRETS_DIR,
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
        """Return the settings sources, highest priority first.

        The order is init kwarg, environment variable, dotenv entry, secret file,
        then YAML profile; each overrides the ones after it. Secret files are read
        from the directory ``SECRETS_DIR`` names, keyed by the same canonical
        ``__``-nested variable names their environment twins use.

        ``FASTAPI_ENV`` selects the YAML profile block, and is read from the same
        three sources in the same order, so the block loaded always matches the
        value the resolved settings report.

        :param settings_cls: The settings class being configured.
        :param init_settings: The init-arguments source.
        :param env_settings: The environment-variable source.
        :param dotenv_settings: The dotenv-file source.
        :param file_secret_settings: The file-secret source the secret-file source
            derives its directory and settings class from.
        :return: The settings sources, ordered highest-priority first.
        :raises SettingsError: When ``SECRETS_DIR`` names a path that is not a
            directory, or one whose contents exceed the source's size ceiling.
        """
        secret_settings = NestedSecretsSettingsSource(file_secret_settings)
        env_key = "fastapi_env"
        yaml_prefix = (
            env_settings.env_vars.get(env_key)
            or dotenv_settings.env_vars.get(env_key)
            or secret_settings.env_vars.get(env_key, pre_env_settings.FASTAPI_ENV)
        )
        if cls.SETTINGS_PREFIXES:
            env_prefix = "__".join(cls.SETTINGS_PREFIXES).lower()
            for env_source in [env_settings, dotenv_settings, secret_settings]:
                env_vars = {}
                for key, value in env_source.env_vars.items():
                    env_vars[
                        re.sub(f"^{env_prefix}__([a-zA-Z0-9_-]+)$", r"\1", key)
                    ] = value
                env_source.env_vars = env_vars
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            secret_settings,
            YamlPrefixConfigSettingsSource(
                settings_cls,
                prefixes=(yaml_prefix, *cls.SETTINGS_PREFIXES),
            ),
        )


T = TypeVar("T", bound=BaseRemoteAPI)


class PMMSettings(BaseLowercaseModel):
    """Define core PMM connection and authentication configuration.

    :param endpoint: The PMM server URL.
    :type endpoint: StrCredentialHttpUrl | None
    :param frontend: The PMM frontend URL.
    :type frontend: StrHttpUrl | None
    :param api_key: API key for PMM authentication.
    :type api_key: SecretStr | None
    :param verify_ssl: Whether to verify SSL certificates.
    :type verify_ssl: bool
    :param execution_target: Explicit execution target name or address for PMM tasks.
    :type execution_target: str | None
    :param annotations_enabled: Whether to create PMM annotations for task lifecycle
        events.
    :type annotations_enabled: bool
    :param annotations_timeout: Timeout in seconds for PMM annotation API calls.
    :type annotations_timeout: PositiveInt
    """

    endpoint: StrCredentialHttpUrl | None = None
    frontend: StrHttpUrl | None = hot_field(None, advanced=True)
    api_key: SecretStr | None = None
    verify_ssl: bool = hot_field(default=True, advanced=True)
    execution_target: str | None = hot_field(None, advanced=True)
    annotations_enabled: bool = hot_field(default=False, advanced=True)
    annotations_timeout: PositiveInt = hot_field(5, advanced=True)

    @model_validator(mode="after")
    def _default_frontend_to_endpoint(self) -> Self:
        """Set ``frontend`` to ``endpoint`` when not explicitly provided.

        :return: The updated settings instance.
        :rtype: Self
        """
        if "frontend" not in self.model_fields_set and self.endpoint is not None:
            self.frontend = self.endpoint
        return self

    @cached_property
    def hostname(self) -> str | None:
        """Extract and return the hostname from the PMM endpoint.

        :return: The hostname of the PMM endpoint, or ``None`` if not set.
        :rtype: str | None
        """
        if self.endpoint:
            return urlparse(self.endpoint).hostname
        return None


_INTERNAL_TOKEN_LABEL = b"sep-internal-token"

SettingsOverrideKey = Annotated[str, StringConstraints(pattern=r"^[^\s.]+\.[^\s.]+$")]


class Settings(BaseYamlSettings):
    """Define the main application settings.

    :param CELERY: Celery configuration options.
    :param ALLOW_CONCURRENT_SESSIONS: Whether to allow concurrent sessions for the same
        user. Defaults to False, meaning all previous sessions will be invalidated once
        a new one is created.
    :param SECRET_KEY: The secret key used for signing tokens. Defaults to
        ``secrets.token_urlsafe(32)``.
    :param SEP_INTERNAL_TOKEN: A long random secret used for SEP-internal
        service-to-service authentication (e.g. scheduled inventory sync). When
        unset, it is derived from ``SECRET_KEY`` by ``derive_internal_token`` so
        every process sharing ``SECRET_KEY`` resolves the identical token.
        Generate an explicit value with ``openssl rand -hex 32`` to rotate it
        independently of ``SECRET_KEY``.
    :param LOGGING: The logging level for the application. Defaults to LogLevel.WARNING.
    :param LOGGING_CONFIG: dictConfig logging configuration.
    :param SSL_CAFILE: The SSL CA file to use for remote API requests.
    :param BASE_URL: The application's base URL.
    :param BACKEND_CORS_ORIGINS: A global list of allowed CORS origins, to be used as
        the default BACKEND_CORS_ORIGINS setting across all apps.
    :param ALLOWED_HOSTS: A global list of trusted domain names or wildcards, to be used
        as the default ALLOWED_HOSTS setting across all apps.
    :param SECURITY_HEADERS: Global options for the SecurityHeadersMiddleware, to be
        used as the default SECURITY_HEADERS setting across all apps.
    :param PMM: PMM connection and authentication configuration.
    :param SETTINGS_OVERRIDE_REFRESH_INTERVAL: How often each service refreshes its
        DB-backed setting overrides. Defaults to 30 seconds.
    :param SETTINGS_OVERRIDE_REFRESHER_ENABLED: Master kill-switch for the DB-override
        background refresher. Tests set this to ``False`` to keep ``TestClient``
        lifespans hermetic; production leaves it ``True``.
    :param SETTINGS_OVERRIDE_ALLOWED_KEYS: The exhaustive set of settings keys the
        override API may write, each spelled ``"<SettingsClassName>.<KEY>"`` (the
        key being a top-level field name or a ``__``-delimited nested path).
        ``None``, the default, places no restriction. A set activates a
        default-locked allowlist: any pair it does not name is refused. The
        allowlist only ever *restricts*: a field that is already not overridable
        stays that way even when listed. Whether the named class and field exist
        is not checked at load time, so a typo'd entry allows nothing rather than
        raising; whitespace anywhere in an entry is rejected outright, since such
        an entry reads correct but matches nothing.
    """

    CELERY: CeleryOptions
    ALLOW_CONCURRENT_SESSIONS: bool = False
    SECRET_KEY: SecretStr = SecretStr(secrets.token_urlsafe(32))
    SEP_INTERNAL_TOKEN: SecretStr | None = None
    LOGGING: LogLevel = hot_field(LogLevel.WARNING)
    LOGGING_CONFIG: dict[str, Any] = {}
    SSL_CAFILE: RelativeFilePathField | None = None
    BASE_URL: URL | None = None
    BACKEND_CORS_ORIGINS: list[StrHttpUrl] | None = None
    ALLOWED_HOSTS: list[str] = []
    SECURITY_HEADERS: SecurityHeadersOptions | None = SecurityHeadersOptions()
    PMM: PMMSettings = hot_field(PMMSettings())
    SETTINGS_OVERRIDE_REFRESH_INTERVAL: TimedeltaSeconds = timedelta(seconds=30)
    SETTINGS_OVERRIDE_REFRESHER_ENABLED: bool = True
    SETTINGS_OVERRIDE_ALLOWED_KEYS: set[SettingsOverrideKey] | None = (
        not_overridable_field(None)
    )
    _CLIENT_REGISTRY: ClientRegistry = ClientRegistry()

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

    @field_validator("SETTINGS_OVERRIDE_REFRESH_INTERVAL")
    @classmethod
    def _settings_override_refresh_interval_positive(
        cls, value: timedelta
    ) -> timedelta:
        """Reject zero or negative refresh intervals.

        ``start_refresh_task()`` passes ``interval.total_seconds()`` directly
        to ``asyncio.sleep()``. A non-positive interval would turn the
        refresher into a tight loop that hammers the DB every iteration.

        :param value: The configured refresh interval.
        :type value: timedelta
        :return: The validated interval.
        :rtype: timedelta
        :raises ValueError: If ``value`` is not strictly positive.
        """
        if value.total_seconds() <= 0:
            raise ValueError(
                "SETTINGS_OVERRIDE_REFRESH_INTERVAL must be a positive duration"
            )
        return value

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

    @model_validator(mode="after")
    def derive_internal_token(self) -> Self:
        """Derive ``SEP_INTERNAL_TOKEN`` from ``SECRET_KEY`` when it is unset.

        Every process sharing ``SECRET_KEY`` derives the identical token via
        HMAC-SHA256, so SEP-internal service-to-service authentication works
        across the web apps and the lifespan-less Celery worker without
        persisting or distributing a separate secret. An explicitly configured
        ``SEP_INTERNAL_TOKEN`` takes precedence so it can be rotated
        independently.

        :return: Validated settings with ``SEP_INTERNAL_TOKEN`` guaranteed set.
        :raises ValueError: If ``SEP_INTERNAL_TOKEN`` is unset and ``SECRET_KEY``
            is empty, so no token can be derived.
        """
        if (
            self.SEP_INTERNAL_TOKEN is not None
            and self.SEP_INTERNAL_TOKEN.get_secret_value()
        ):
            return self
        secret_key = self.SECRET_KEY.get_secret_value()
        if not secret_key:
            raise ValueError(
                "SECRET_KEY must be set to a non-empty value so SEP_INTERNAL_TOKEN "
                "can be derived for service-to-service authentication "
                "(e.g. `openssl rand -hex 32`)."
            )
        derived = hmac.new(
            secret_key.encode(), _INTERNAL_TOKEN_LABEL, hashlib.sha256
        ).hexdigest()
        self.SEP_INTERNAL_TOKEN = SecretStr(derived)
        return self

    @validate_call
    async def get_remote_api(
        self,
        cls: type[T] = RemoteAPI,
        **kwargs: Any,
    ) -> T:
        """Get or create a RemoteAPI client instance.

        :param cls: The class of the RemoteAPI client. Defaults to :class:`RemoteAPI`.
        :type cls: type[T]
        :param kwargs: Additional keyword arguments to configure the RemoteAPI client.
        :type kwargs: Any
        :return: An instance of the requested RemoteAPI client.
        :rtype: T
        """
        logger.debug(
            "Getting remote API client from registry for %s with kwargs %s",
            cls.__name__,
            _sanitize_client_kwargs(kwargs),
        )
        return await self._CLIENT_REGISTRY.get(cls, **kwargs)

    async def invalidate_client(self, endpoint: str) -> None:
        """Evict every cached remote-API client served from ``endpoint``.

        Thin wrapper over :meth:`ClientRegistry.invalidate` used by override
        rebind callbacks to drop clients (e.g. PMM) whose connection settings
        changed at runtime, so the next request reconstructs a fresh client.

        :param endpoint: The endpoint URL whose cached clients to evict.
        :type endpoint: str
        """
        await self._CLIENT_REGISTRY.invalidate(endpoint)

    async def close_client_registry(self) -> None:
        """Close the client registry and all its managed clients."""
        await self._CLIENT_REGISTRY.close_all()


def _create_settings() -> Settings:
    """Create a :class:`Settings` instance and apply its logging configuration."""
    s = Settings()
    logging.config.dictConfig(s.LOGGING_CONFIG)
    return s


settings: Settings = OverridableSettingsProxy(
    _create_settings, setting_class=SettingClassEnum.SETTINGS
)
logger = logging.getLogger(__name__)


class BaseYamlAppSettings(BaseYamlSettings):
    """Define base settings for a FastAPI app.

    :cvar SETTINGS_PREFIXES: Tuple of settings prefixes.
    :vartype SETTINGS_PREFIXES: list[str]
    :param UVICORN_HOST: The host for Uvicorn. Defaults to "127.0.0.1".
    :type UVICORN_HOST: str
    :param UVICORN_PORT: The port for Uvicorn. Defaults to 0.
    :type UVICORN_PORT: int
    :param UVICORN_RELOAD: Enable auto-reload on file changes. Defaults to ``False``.
        Set to ``True`` in development for hot-reloading.
    :type UVICORN_RELOAD: bool
    :param UVICORN_EXTRA_RELOAD_DIRS: Additional directories for uvicorn to watch when
        ``UVICORN_RELOAD`` is enabled. Appended to the hardcoded base directories.
        Defaults to ``[]``.
    :type UVICORN_EXTRA_RELOAD_DIRS: list[str]
    :param UVICORN_EXTRA_RELOAD_INCLUDES: Additional glob patterns for uvicorn to include
        when watching for changes. Appended to the hardcoded base includes.
        Defaults to ``[]``.
    :type UVICORN_EXTRA_RELOAD_INCLUDES: list[str]
    :param UVICORN_EXTRA_RELOAD_EXCLUDES: Additional glob patterns for uvicorn to exclude
        when watching for changes. Appended to the hardcoded base excludes.
        Defaults to ``[]``.
    :type UVICORN_EXTRA_RELOAD_EXCLUDES: list[str]
    :param SSL_KEYFILE: Path to the SSL key file. Defaults to None.
    :type SSL_KEYFILE: RelativeFilePathField | None
    :param SSL_CERTFILE: Path to the SSL certificate file. Defaults to None.
    :type SSL_CERTFILE: RelativeFilePathField | None
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
    UVICORN_RELOAD: bool = False
    UVICORN_EXTRA_RELOAD_DIRS: list[str] = []
    UVICORN_EXTRA_RELOAD_INCLUDES: list[str] = []
    UVICORN_EXTRA_RELOAD_EXCLUDES: list[str] = []
    SSL_KEYFILE: RelativeFilePathField | None = None
    SSL_CERTFILE: RelativeFilePathField | None = None
    BACKEND_CORS_ORIGINS: list[StrHttpUrl] | None = Field(
        default_factory=lambda: settings.BACKEND_CORS_ORIGINS
    )
    ALLOWED_HOSTS: list[str] = Field(
        default_factory=lambda: settings.ALLOWED_HOSTS, min_length=1
    )
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

    Ensures that the active auth provider's SDK and any extra client sessions are
    properly managed during the application's startup and shutdown phases.

    :param app: The FastAPI application instance.
    :yield: None
    """
    # lazy import: auth/config.py imports BaseYamlSettings from this module, so a
    # module-level import here would cycle
    from app.core.auth.config import get_active_auth_provider

    async with get_active_auth_provider().lifespan():
        yield
    await settings.close_client_registry()


class _UnsetType:
    """Sentinel type for unset ``create_app`` parameters.

    Distinguishes "caller did not pass this argument" from "caller passed ``None``"
    so we can preserve FastAPI's own defaults when the parameter is omitted while
    still letting callers explicitly set the value to ``None``.
    """

    _instance: "_UnsetType | None" = None

    def __new__(cls) -> "_UnsetType":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "_UNSET"


_UNSET = _UnsetType()


def create_app(
    *routers: APIRouter,
    lifespan: Lifespan[AppType] | None = None,
    backend_cors_origins: list[StrHttpUrl] | None = None,
    allowed_hosts: list[str] | None = None,
    security_headers: SecurityHeadersOptions | None = None,
    title: str | None = None,
    version: str | None = None,
    description: str | None = None,
    generate_unique_id_function: Callable[[APIRoute], str] | None = None,
    docs_url: str | None | _UnsetType = _UNSET,
    redoc_url: str | None | _UnsetType = _UNSET,
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
    :param title: Optional OpenAPI title for the generated spec.
    :type title: str | None
    :param version: Optional OpenAPI version string.
    :type version: str | None
    :param description: Optional OpenAPI description text.
    :type description: str | None
    :param generate_unique_id_function: Optional callback for stable ``operationId``
        values. When omitted, :func:`app.core.utils.openapi.generate_tag_prefixed_unique_id`
        is used so similarly named handlers across routers do not collide.
    :type generate_unique_id_function: Callable[[APIRoute], str] | None
    :param docs_url: Override for FastAPI's ``docs_url`` parameter. Pass ``None`` to
        disable the auto-generated Swagger UI. When omitted, FastAPI's default of
        ``"/docs"`` is preserved.
    :type docs_url: str | None | _UnsetType
    :param redoc_url: Override for FastAPI's ``redoc_url`` parameter. Pass ``None`` to
        disable the auto-generated ReDoc UI. When omitted, FastAPI's default of
        ``"/redoc"`` is preserved.
    :type redoc_url: str | None | _UnsetType
    :return: An instance of the FastAPI application with an attached Celery app.
    :rtype: FastAPI
    """
    openapi_kwargs = {}
    if title is not None:
        openapi_kwargs["title"] = title
    if version is not None:
        openapi_kwargs["version"] = version
    if description is not None:
        openapi_kwargs["description"] = description
    openapi_kwargs["generate_unique_id_function"] = (
        generate_unique_id_function or generate_tag_prefixed_unique_id
    )
    if docs_url is not _UNSET:
        openapi_kwargs["docs_url"] = docs_url
    if redoc_url is not _UNSET:
        openapi_kwargs["redoc_url"] = redoc_url
    app = FastAPI(lifespan=lifespan, **openapi_kwargs)
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
    install_namespaced_openapi(app)
    return app
