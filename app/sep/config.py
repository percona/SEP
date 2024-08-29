"""Define SEP settings."""

from pathlib import Path
from typing import Annotated
from typing import Self

from pydantic import BaseModel
from pydantic import Field
from pydantic import HttpUrl
from pydantic import model_validator

from app.core.config import BaseYamlExtraSettings
from app.core.config import settings
from app.core.fields import RelativeDirectoryPath


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
    POST_LOGIN_URI: HttpUrl | Annotated[str, Field(pattern=r"^\/[^\s]*$")] = "/"
    AUTH_LINK: str = ""
    COOKIE_NAME: str = "authToken"

    @model_validator(mode="after")
    def _set_default_auth_link(self) -> Self:
        if not self.AUTH_LINK:
            self.AUTH_LINK = settings.CASDOOR.SYNC_SDK.get_auth_link(
                self.REDIRECT_URI,
            )
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

    """

    OAUTH: OAuthOptions
    TEMPLATES_DIR: RelativeDirectoryPath = Path("templates")
    STATIC_DIR: RelativeDirectoryPath = Path("static")
    INVENTORY_ENDPOINT: HttpUrl
    TASKS_ENDPOINT: HttpUrl


sep_settings = SEPSettings()
