"""Define SEP settings."""

from functools import cached_property
from pathlib import Path
from typing import Self
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pydantic import computed_field
from pydantic import Field
from pydantic import field_validator
from pydantic import HttpUrl
from pydantic import model_validator

from app.core.config import BaseYamlExtraSettings
from app.core.config import settings
from app.core.fields import RelativeDirectoryPath
from app.core.fields import RelativeFilePath
from app.core.fields import URIPath
from app.sep.models import Plugin


# TODO: Adjust/correct/complete docstrings
class OAuthOptions(BaseModel):
    """Configuration options for OAuth2 authentication.

    Attributes
    ----------
    REDIRECT_URI : str
        The URI to redirect from OAuth.
    POST_LOGIN_URI : str, optional
        The URI to redirect to after login. Defaults to "/".
    AUTH_LINK : str, optional
        The OAuth link for authentication.
        Defaults to `CasdoorOptions.SYNC_SDK.get_auth_link(REDIRECT_URI)`.
    COOKIE_NAME : str, optional
        The key of the authentication cookie. Defaults to "authToken".

    """

    REDIRECT_URI: HttpUrl
    POST_LOGIN_URI: HttpUrl | URIPath = "/"
    AUTH_LINK: str = ""
    COOKIE_NAME: str = "authToken"

    @model_validator(mode="after")
    def _set_default_auth_link(self) -> Self:
        if not self.AUTH_LINK:
            url = settings.CASDOOR.FRONT_ENDPOINT + "/login/oauth/authorize?"
            params = {
                "client_id": settings.CASDOOR.CLIENT_ID,
                "response_type": "code",
                "redirect_uri": self.REDIRECT_URI,
                "scope": "read",
                "state": settings.CASDOOR.APPLICATION_NAME,
            }
            self.AUTH_LINK = url + urlencode(params)
        return self


class SEPSettings(BaseYamlExtraSettings):
    """Settings for SEP.

    Attributes
    ----------
    OAUTH : OAuthOptions
        OAuth configuration options.
    TEMPLATES_DIR : Path, optional
        The directory containing template files. Defaults to `BASE_DIR/"templates"`
    STATIC_DIR : Path, optional
        The directory containing static files. Defaults to `BASE_DIR/"static"`
    ALTERS_DB_USERNAME : str, optional
        The username for accessing the Alters database. Defaults to `None`.
    ALTERS_DB_PASSWORD : str, optional
        The password for accessing the Alters database. This field is automatically
        escaped to handle special characters. Defaults to `None`.
    PLUGINS : list of Plugin, optional
        A list of plugins used by SEP. Defaults to an empty list.
    TEMPLATES

    """

    OAUTH: OAuthOptions
    TEMPLATES_DIR: RelativeDirectoryPath = Path("templates")
    STATIC_DIR: RelativeDirectoryPath = Path("static")
    INVENTORY_ENDPOINT: HttpUrl
    TASKS_ENDPOINT: HttpUrl
    SEP_ENDPOINT: HttpUrl = Field(default="http://0.0.0.0:8000", validate_default=True)
    ALTERS_DB_USERNAME: str | None = None
    ALTERS_DB_PASSWORD: str | None = None
    PLUGINS: set[Plugin] = set()
    PROXY_HEADERS: bool = False
    SSL_KEYFILE: RelativeFilePath | None = None
    SSL_CERTFILE: RelativeFilePath | None = None

    @field_validator("ALTERS_DB_PASSWORD")
    @classmethod
    def escape_db_password(cls, v: str | None) -> str:
        """Escape special characters in the database password.

        This method replaces commas in the database password with an escaped version
        to ensure proper handling in connection strings.

        Parameters
        ----------
        v : str or None
            The original database password.

        Returns
        -------
        str
            The escaped database password if `v` is not `None`, otherwise `None`.

        """
        if v is not None:
            return v.replace(",", "\\,")

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


sep_settings = SEPSettings()
