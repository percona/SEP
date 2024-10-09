"""Define SEP settings."""

from copy import deepcopy
from datetime import timedelta
from functools import cached_property
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import ClassVar
from typing import Literal
from typing import Self
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates
from pydantic import AfterValidator
from pydantic import AliasGenerator
from pydantic import BaseModel
from pydantic import computed_field
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import HttpUrl
from pydantic import model_validator

from app.core.config import BaseCaseInsensitiveModel
from app.core.config import BaseLowercaseModel
from app.core.config import BaseYamlExtraSettings
from app.core.config import settings
from app.core.db.config import DatabaseOptions
from app.core.fields import RelativeDirectoryPath
from app.core.fields import remove_duplicates
from app.core.fields import StrImportableAttribute
from app.core.fields import TimedeltaSeconds
from app.core.fields import URIPath
from app.core.fields import URL
from app.core.utils import deep_dict_update
from app.sep.models import Plugin


class OAuthOptions(BaseModel):
    """Configuration options for OAuth2 authentication.

    Attributes
    ----------
    REDIRECT_URI : HttpUrl or URIPath
        The URI to redirect from OAuth.
    POST_LOGIN_URI : HttpUrl or URIPath, optional
        The URI to redirect to after login. Defaults to "/".
    AUTH_LINK : str, optional
        The OAuth link for authentication.
        Defaults to an empty string.

    """

    REDIRECT_URI: HttpUrl | URIPath
    POST_LOGIN_URI: HttpUrl | URIPath = "/"
    AUTH_LINK: str = ""

    def get_auth_url(self, base_url: URL | None = None) -> str:
        """Return the OAuth2 authorization URL for user authentication.

        If `self.AUTH_LINK` is defined and not empty, return it. Otherwise, construct
        the OAuth2 authorization URL with `settings.CASDOOR.get_frontend_url(base_url)`.


        Parameters
        ----------
        base_url : URL, optional
            The base URL to be used for constructing the authorization URL.
            If `REDIRECT_URL` is a relative path, it will use `base_url` as its base.

        Returns
        -------
        str
            The full OAuth2 authorization URL, containing query parameters for
            Client ID, response type, redirect URI, scope, and state.

        """
        if self.AUTH_LINK:
            return self.AUTH_LINK

        redirect_uri = self.REDIRECT_URI

        if base_url is not None and isinstance(self.REDIRECT_URI, str):
            redirect_uri = base_url.replace(path=redirect_uri)

        params = {
            "client_id": settings.CASDOOR.CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "read",
            "state": settings.CASDOOR.APPLICATION_NAME,
        }
        url = settings.CASDOOR.get_frontend_url(base_url).replace(
            path="/login/oauth/authorize",
            query=urlencode(params),
        )
        return str(url)


class SessionOptions(BaseCaseInsensitiveModel):
    """Configuration options for a SEP session.

    Attributes
    ----------
    COOKIE_NAME : str, optional
        The key of the authentication cookie. Defaults to "authToken".
    MAX_AGE : timedelta, optional
        Maximum age of the session cookie. Defaults to 7 days.
    SAMESITE : {'lax', 'strict', 'none'}, optional
        SameSite policy for the session cookie. Defaults to 'lax'.
    SECURE : bool, optional
        Whether the session cookie should be accessible only via HTTPS.
        Defaults to False.

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

    Attributes
    ----------
    syncer : StrImportableAttribute
        The importable attribute name for the synchronizer. This field is automatically
        prefixed with "app.sep.sync.syncers." during validation.

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

        Parameters
        ----------
        v : str
            The base syncer name provided.

        Returns
        -------
        str
            The fully qualified path for the synchronizer.

        """
        root = "app.sep.sync.syncers."
        if not v.startswith(root):
            v = root + v
        return v


class SEPSettings(BaseYamlExtraSettings):
    """Settings for SEP.

    Attributes
    ----------
    UVICORN_PORT : int, optional
        The port number used by the Uvicorn server. Defaults to 8000.
    OAUTH : OAuthOptions
        OAuth configuration options.
    SESSION : SessionOptions
        Session configuration options.
    TEMPLATES_DIR : Path, optional
        The directory containing template files. Defaults to `BASE_DIR/"templates"`.
    STATIC_DIR : Path, optional
        The directory containing static files. Defaults to `BASE_DIR/"static"`.
    INVENTORY_ENDPOINT : HttpUrl
        The endpoint URL for the Inventory API.
    TASKS_ENDPOINT : HttpUrl
        The endpoint URL for the Tasks API.
    PLUGINS : set of Plugin, optional
        A set of plugins used by SEP. Defaults to an empty set.
    PROXY_HEADERS : bool, optional
        Whether to use proxy headers (like `X-Forwarded-For`). Defaults to `False`.
    DATABASE : DatabaseOptions
        The database configuration options.
        Defaults to an SQLite database with the name 'sep.db'.
    SYNCERS : list of SyncOptions
        A list of synchronizers used by SEP. Defaults to an empty list with duplicates
        removed.
    SYNCER_EXTRA_KWARGS : dict[str, Any]
        Additional keyword arguments for synchronizers. Defaults to an empty dictionary.
    TEMPLATES

    """

    SETTINGS_PREFIXES: ClassVar[tuple[str]] = ("SEP",)
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

    @computed_field
    @cached_property
    def TEMPLATES(self) -> Jinja2Templates:
        """Return a Jinja2Templates object for template rendering.

        This property creates, caches, and returns a `Jinja2Templates` object configured
        with the `TEMPLATES_DIR` directory.

        Returns
        -------
        Jinja2Templates
            The Jinja2 templates object for rendering templates.

        """
        return Jinja2Templates(directory=sep_settings.TEMPLATES_DIR)

    @model_validator(mode="after")
    def add_syncer_extra_kwargs(self) -> Self:
        """Integrate extra keyword arguments into synchronizers.

        Merge additional keyword arguments from `SYNCER_EXTRA_KWARGS` into each
        synchronizer in `SYNCERS` and update the list accordingly.

        Returns
        -------
        Self
            The updated `SEPSettings` instance with modified `SYNCERS`.

        """
        syncers = []
        for syncer in self.SYNCERS:
            syncer_data = deepcopy(self.SYNCER_EXTRA_KWARGS)
            deep_dict_update(syncer_data, syncer.model_dump())
            syncers.append(SyncOptions.model_validate(syncer_data))
        self.SYNCERS = syncers
        return self


sep_settings = SEPSettings()
