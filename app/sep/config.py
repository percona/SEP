"""Define SEP settings."""

from copy import deepcopy
from datetime import timedelta
from functools import cached_property
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal, Self
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from pydantic import (
    AfterValidator,
    AliasGenerator,
    BaseModel,
    computed_field,
    ConfigDict,
    Field,
    field_validator,
    HttpUrl,
    model_validator,
)

from app.core.config import (
    BaseYamlExtraSettings,
    settings,
)
from app.core.db.config import DatabaseOptions
from app.core.fields import (
    RelativeDirectoryPath,
    remove_duplicates,
    StrImportableAttribute,
    TimedeltaSeconds,
    URIPath,
    URL,
)
from app.core.models import BaseCaseInsensitiveModel, BaseLowercaseModel
from app.core.utils import deep_dict_update
from app.sep.models import Plugin


class OAuthOptions(BaseModel):
    """Configuration options for OAuth2 authentication.

    :param REDIRECT_URI: The URI to redirect from OAuth.
    :type REDIRECT_URI: HttpUrl | URIPath
    :param POST_LOGIN_URI: The URI to redirect to after login. Defaults to "/".
    :type POST_LOGIN_URI: HttpUrl | URIPath
    :param AUTH_LINK: The OAuth link for authentication. Defaults to an empty string.
    :type AUTH_LINK: str
    """

    REDIRECT_URI: HttpUrl | URIPath
    POST_LOGIN_URI: HttpUrl | URIPath = "/"
    AUTH_LINK: str = ""

    def get_auth_url(self, base_url: URL | None = None) -> str:
        """Return the OAuth2 authorization URL for user authentication.

        If `self.AUTH_LINK` is defined and not empty, return it. Otherwise, construct
        the OAuth2 authorization URL with `settings.CASDOOR.get_frontend_url(base_url)`.

        :param base_url: The base URL to be used for constructing the authorization URL.
            If `REDIRECT_URI` is a relative path, it will use `base_url` as its base.
        :type base_url: Any
        :return: The full OAuth2 authorization URL, containing query parameters for
            Client ID, response type, redirect URI, scope, and state.
        :rtype: str
        """
        if self.AUTH_LINK:
            return self.AUTH_LINK

        redirect_uri = self.REDIRECT_URI

        if base_url is not None and isinstance(self.REDIRECT_URI, str):
            redirect_uri = base_url.replace(path=redirect_uri)

        params = {
            "client_id": settings.CASDOOR.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "read",
            "state": settings.CASDOOR.application_name,
        }
        url = settings.CASDOOR.get_frontend_url(base_url).replace(
            path="/login/oauth/authorize",
            query=urlencode(params),
        )
        return str(url)


class SessionOptions(BaseCaseInsensitiveModel):
    """Configuration options for a SEP session.

    :param COOKIE_NAME: The key of the authentication cookie. Defaults to "authToken".
    :type COOKIE_NAME: str
    :param MAX_AGE: Maximum age of the session cookie. Defaults to 7 days.
    :type MAX_AGE: TimedeltaSeconds
    :param SAMESITE: SameSite policy for the session cookie. Defaults to 'lax'.
    :type SAMESITE: Literal["lax", "strict", "none"]
    :param SECURE: Whether the session cookie should be accessible only via HTTPS.
        Defaults to False.
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
    SECURE: bool = False


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


class SEPSettings(BaseYamlExtraSettings):
    """Settings for SEP.

    :param SETTINGS_PREFIXES: The prefixes for SEP-related settings in the configuration
        file. Set to ["SEP"].
    :type SETTINGS_PREFIXES: ClassVar[list[str]]
    :param UVICORN_PORT: The port number used by the Uvicorn server. Defaults to 8000.
    :type UVICORN_PORT: int
    :param OAUTH: OAuth configuration options.
    :type OAUTH: OAuthOptions
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
    :type PLUGINS: list[Plugin]
    :param PROXY_HEADERS: Whether to use proxy headers (like `X-Forwarded-For`).
        Defaults to `False`.
    :type PROXY_HEADERS: bool
    :param DATABASE: The database configuration options.
        Defaults to an SQLite database with the name 'sep.db'.
    :type DATABASE: DatabaseOptions
    :param SYNCERS: A list of synchronizers used by SEP. Defaults to an empty list with
        duplicates removed.
    :type SYNCERS: list[SyncOptions]
    :param SYNCER_EXTRA_KWARGS: Additional keyword arguments for synchronizers. Defaults
        to an empty dictionary.
    :type SYNCER_EXTRA_KWARGS: dict[str, Any]
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["SEP"]
    UVICORN_PORT: int = 8000
    OAUTH: OAuthOptions
    SESSION: SessionOptions = SessionOptions()
    TEMPLATES_DIR: RelativeDirectoryPath = Path("templates")
    STATIC_DIR: RelativeDirectoryPath = Path("static")
    INVENTORY_ENDPOINT: HttpUrl
    TASKS_ENDPOINT: HttpUrl
    PLUGINS: Annotated[list[Plugin], AfterValidator(remove_duplicates)] = []
    PROXY_HEADERS: bool = False
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="sep.db")
    SYNCERS: Annotated[list[SyncOptions], AfterValidator(remove_duplicates)] = []
    SYNCER_EXTRA_KWARGS: dict[str, Any] = {}
    SYNC_REFRESH_TIME: int = 5

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
            env=Environment(
                loader=FileSystemLoader(sep_settings.TEMPLATES_DIR),
                autoescape=True,
                extensions=["jinja2.ext.do"],
            )
        )

    @model_validator(mode="after")
    def add_syncer_extra_kwargs(self) -> Self:
        """Integrate extra keyword arguments into synchronizers.

        Merge additional keyword arguments from `SYNCER_EXTRA_KWARGS` into each
        synchronizer in `SYNCERS` and update the list accordingly.

        :return: The updated `SEPSettings` instance with modified `SYNCERS`.
        :rtype: Self
        """
        syncers = []
        for syncer in self.SYNCERS:
            syncer_data = deepcopy(self.SYNCER_EXTRA_KWARGS)
            deep_dict_update(syncer_data, syncer.model_dump())
            syncers.append(SyncOptions.model_validate(syncer_data))
        self.SYNCERS = syncers
        return self


sep_settings = SEPSettings()
