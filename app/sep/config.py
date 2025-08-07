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
    ValidationError,
)

from app.core.config import (
    BaseYamlAppSettings,
    settings,
)
from app.core.db.config import DatabaseOptions
from app.core.models import BaseLowercaseModel
from app.core.utils import deep_dict_update, run_pydantic_type_validator
from app.core.utils.fields import (
    RelativeDirectoryPath,
    StrHttpUrl,
    StrImportableAttribute,
    TimedeltaSeconds,
    UniqueList,
)
from app.sep.models import Plugin
from app.sep.utils.jinja import syntax_highlight, syntax_highlight_css


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

    :param secret_key: Secret key used for CSRF token generation.
    :type secret_key: str
    :param cookie_secure: Whether the CSRF cookie should be accessible
        only via HTTPS (except on localhost).
    :type cookie_secure: bool
    :param cookie_samesite: SameSite policy for the CSRF cookie.
    :type cookie_samesite: str
    :param token_key: Key name for the CSRF token.
    :type token_key: str
    :param token_location: Location where the CSRF token is expected.
    :type token_location: str
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
        env.filters["syntax_highlight"] = syntax_highlight
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
