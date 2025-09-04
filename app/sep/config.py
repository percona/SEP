# Copyright (C) 2025 Percona LLC
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

"""Define SEP settings."""

from datetime import timedelta
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar, Literal, Self

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from pydantic import (
    AliasGenerator,
    BaseModel,
    computed_field,
    ConfigDict,
    Field,
    field_validator,
    HttpUrl,
    model_validator,
    NonNegativeInt,
    ValidationError,
)

from app.core.config import (
    BaseYamlAppSettings,
    settings,
)
from app.core.db.config import DatabaseOptions
from app.core.models import BaseCaseInsensitiveModel, BaseLowercaseModel
from app.core.utils import (
    deep_dict_update,
    run_pydantic_type_validator,
    slugify,
)
from app.core.utils.fields import (
    RelativeDirectoryPath,
    StrHttpUrl,
    StrImportableAttribute,
    StrImportableModule,
    TimedeltaSeconds,
    UniqueList,
    URIPath,
)
from app.sep.utils.jinja import DEFAULT_FILTERS, syntax_highlight_css


class Plugin(BaseCaseInsensitiveModel):
    """Represent a SEP plugin.

    This model defines the structure for a plugin, including its name, module,
    URI path, and CSS class. It includes custom validators to resolve the module
    path and set default values based on the plugin's name.

    :param name: The name of the plugin.
    :type name: str
    :param module_name: The name of the module associated with the plugin. This field is
        automatically prefixed with "app.sep.plugins." during validation.
    :type module_name: StrImportableModule
    :param uri_path: The URI path where the plugin is accessible. Defaults to an empty
        string, but is automatically set to a slugified version of the plugin name if
        not provided.
    :type uri_path: HttpUrl | URIPath
    :param css_class: The CSS class associated with the plugin. Defaults to an empty
        string, but is automatically set to a slugified version of the plugin name if
        not provided.
    :type css_class: str
    :param sidebar: Whether to add this plugin to the sidebar. Defaults to True.
    :type sidebar: bool
    """

    name: str
    module_name: StrImportableModule
    uri_path: HttpUrl | URIPath = ""
    css_class: str = ""
    sidebar: bool = True

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Plugin):
            return self.module_name == other.module_name
        raise NotImplementedError

    @field_validator("module_name", mode="before")
    @classmethod
    def resolve_module_path(cls, v: str) -> str:
        """Resolve the full module path for the plugin.

        This method takes the module name provided and prefixes it with
        "app.sep.plugins." to resolve the full import path.

        :param v: The module name to resolve.
        :type v: str
        :return: The full module path with the "app.sep.plugins." prefix.
        :rtype: str
        """
        return f"app.sep.plugins.{v}"

    @model_validator(mode="before")
    @classmethod
    def _set_default_from_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and (name := data.get("name")):
            slug = slugify(name)
            data["uri_path"] = data.get("uri_path") or f"/{slug}"
            data["css_class"] = data.get("css_class") or slug
        return data

    @computed_field
    @property
    def router_path(self) -> str:
        """Return the plugin's router path.

        :return: The router path derived from the module name.
        :rtype: str
        """
        return f"{self.module_name}.router"


class SessionOptions(BaseModel):
    """Configuration options for a SEP session.

    :param COOKIE_NAME: The key of the authentication cookie. Defaults to "authToken".
    :type COOKIE_NAME: str
    :param MAX_AGE: Maximum age of the session cookie. Defaults to 7 days.
    :type MAX_AGE: TimedeltaSeconds
    :param SAMESITE: SameSite policy for the session cookie. Defaults to 'lax'.
    :type SAMESITE: Literal["lax", "strict", "none"]
    :param SECURE: Whether the session cookie should be accessible only via HTTPS.
        Defaults to True.
    :type SECURE: bool
    """

    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            serialization_alias=lambda field_name: field_name.lower(),
        ),
    )
    COOKIE_NAME: str = Field(default="authToken", serialization_alias="key")
    MAX_AGE: TimedeltaSeconds = timedelta(days=7)
    SAMESITE: Literal["lax", "strict", "none"] = "lax"
    SECURE: bool = True


class CsrfSettings(BaseModel):
    """Configuration for CSRF protection settings.

    :param SECRET_KEY: Secret key used for CSRF token generation.
    :type SECRET_KEY: str
    :param COOKIE_SECURE: Whether the CSRF cookie should be accessible
        only via HTTPS (except on localhost).
    :type COOKIE_SECURE: bool
    :param COOKIE_SAMESITE: SameSite policy for the CSRF cookie.
    :type COOKIE_SAMESITE: str
    :param TOKEN_KEY: Key name for the CSRF token.
    :type TOKEN_KEY: str
    :param TOKEN_LOCATION: Location where the CSRF token is expected.
    :type TOKEN_LOCATION: str
    """

    SECRET_KEY: str = settings.SECRET_KEY
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "none"
    TOKEN_KEY: str = "csrf-token"  # noqa: S105
    TOKEN_LOCATION: str = "body"  # noqa: S105


class SyncOptions(BaseLowercaseModel):
    """Represent a synchronizer for the SEP app.

    This model represents a synchronizer component within the SEP application,
    including its importable attribute and any additional keyword arguments required for
    its operation.

    :param syncer: The importable attribute name for the synchronizer. This field is
        automatically prefixed with "app.sep.sync.syncers." during validation.
    :type syncer: StrImportableAttribute
    """

    model_config = ConfigDict(extra="allow")
    syncer: StrImportableAttribute

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, SyncOptions):
            return self.syncer == other.syncer
        raise NotImplementedError

    @field_validator("syncer", mode="before")
    @classmethod
    def resolve_syncer_path(cls, v: str) -> str:
        """Resolve the full path for the syncer.

        Prefix the provided synchronizer name with "app.sep.sync.syncers." to form the
        complete import path.

        :param v: The base syncer name provided.
        :type v: str
        :return: The fully qualified path for the synchronizer.
        :rtype: str
        """
        root = "app.sep.sync.syncers."
        if not v.startswith(root):
            v = root + v
        return v


class SEPSettings(BaseYamlAppSettings):
    """Settings for SEP.

    :cvar SETTINGS_PREFIXES: The prefixes for SEP-related settings in the configuration
        file. Set to ["SEP"].
    :vartype SETTINGS_PREFIXES: ClassVar[list[str]]
    :param UVICORN_PORT: The port number used by the Uvicorn server. Defaults to 8000.
    :type UVICORN_PORT: int
    :param SESSION: Session configuration options.
    :type SESSION: SessionOptions
    :param TEMPLATES_DIR: The directory containing template files. Defaults to
        `Path("templates")`.
    :type TEMPLATES_DIR: RelativeDirectoryPath
    :param STATIC_DIR: The directory containing static files. Defaults to
        `Path("static")`.
    :type STATIC_DIR: RelativeDirectoryPath
    :param INVENTORY_ENDPOINT: The endpoint URL for the Inventory API.
    :type INVENTORY_ENDPOINT: HttpUrl
    :param TASKS_ENDPOINT: The endpoint URL for the Tasks API.
    :type TASKS_ENDPOINT: HttpUrl
    :param PLUGINS: A list of plugins used by SEP. Defaults to an empty list with
        duplicates removed.
    :type PLUGINS: UniqueList[Plugin]
    :param PROXY_HEADERS: Whether to use proxy headers (like `X-Forwarded-For`).
        Defaults to `False`.
    :type PROXY_HEADERS: bool
    :param DATABASE: The database configuration options.
        Defaults to an SQLite database with the name 'sep.db'.
    :type DATABASE: DatabaseOptions
    :param SYNCERS: A list of synchronizers used by SEP. Defaults to an empty list with
        duplicates removed.
    :type SYNCERS: UniqueList[SyncOptions]
    :param SYNCER_EXTRA_KWARGS: Additional keyword arguments for synchronizers. Defaults
        to an empty dictionary.
    :type SYNCER_EXTRA_KWARGS: dict[str, Any]
    :param SYNC_REFRESH_TIME: The time interval (in seconds) for browser refresh during
        synchronization. Defaults to 5 seconds.
    :type SYNC_REFRESH_TIME: int
    :param PMM_FRONTEND: The URL for the PMM frontend. Defaults to `None`. If not set,
        it will be determined based on the `pmm.endpoint` from the `PMMSyncer` (if
        available).
    :type PMM_FRONTEND: StrHttpUrl | None
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["SEP"]
    UVICORN_PORT: int = 8000
    SESSION: SessionOptions = SessionOptions()
    TEMPLATES_DIR: RelativeDirectoryPath = Path("templates")
    STATIC_DIR: RelativeDirectoryPath = Path("static")
    INVENTORY_ENDPOINT: HttpUrl
    TASKS_ENDPOINT: HttpUrl
    PLUGINS: UniqueList[Plugin] = UniqueList()
    PROXY_HEADERS: bool = False
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="sep.db")
    SYNCERS: UniqueList[SyncOptions] = UniqueList()
    SYNCER_EXTRA_KWARGS: dict[str, Any] = {}
    SYNC_REFRESH_TIME: int = 5
    PMM_FRONTEND: StrHttpUrl | None = None
    MESSAGES_LEVEL: NonNegativeInt = 0

    @computed_field
    @cached_property
    def JINJA_ENVIRONMENT(self) -> Environment:
        """Return a Jinja2 Environment object for templates.

        This property creates, caches, and returns a
        :class:`jinja2.environment.Environment` object configured with the
        `jinja2.ext.do` extension, the `syntax_highlight` filter, and the
        `syntax_highlight_css` utility function as global.

        :return: The Environment configured for Jinja2.
        :rtype: Environment
        """
        env = Environment(
            loader=FileSystemLoader(sep_settings.TEMPLATES_DIR),
            autoescape=True,
            extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
        )
        env.filters |= DEFAULT_FILTERS
        env.globals["syntax_highlight_css"] = syntax_highlight_css
        return env

    @computed_field
    @cached_property
    def TEMPLATES(self) -> Jinja2Templates:
        """Return a Jinja2Templates object for template rendering.

        This property creates, caches, and returns a `Jinja2Templates` object configured
        with the `TEMPLATES_DIR` directory.

        :return: The Jinja2 templates object for rendering templates.
        :rtype: Jinja2Templates
        """
        return Jinja2Templates(
            env=self.JINJA_ENVIRONMENT,
        )

    @model_validator(mode="after")
    def add_syncer_extra_kwargs(self) -> Self:
        """Integrate extra keyword arguments into synchronizers and set PMM_FRONTEND.

        Merge additional keyword arguments from `SYNCER_EXTRA_KWARGS` into each
        synchronizer in `SYNCERS` and update the list accordingly. If `PMM_FRONTEND` is
        not already set, check if `PMMSyncer` is enabled and use the `pmm.endpoint`.

        :return: The updated `SEPSettings` instance with modified `SYNCERS`.
        :rtype: Self
        """
        syncers = UniqueList()
        for syncer in self.SYNCERS:
            syncer_data = syncer.model_dump()
            deep_dict_update(syncer_data, self.SYNCER_EXTRA_KWARGS)
            syncers.append(SyncOptions.model_validate(syncer_data))
            try:
                if (
                    self.PMM_FRONTEND is None
                    and syncer_data["syncer"].endswith("PMMSyncer")
                    and (pmm_endpoint := syncer_data.get("pmm", {}).get("endpoint"))
                ):
                    self.PMM_FRONTEND = run_pydantic_type_validator(
                        StrHttpUrl, pmm_endpoint
                    )
            except AttributeError:
                continue
            except ValidationError:
                raise ValueError("PMM endpoint should be a valid HTTP URL") from None
        self.SYNCERS = syncers
        return self


sep_settings = SEPSettings()
