"""Define the base auth models."""

from datetime import datetime
from datetime import UTC
from functools import cached_property
from typing import Literal
from typing import Self

from pydantic import BaseModel
from pydantic import computed_field
from pydantic import EmailStr
from pydantic import field_validator
from pydantic import FutureDatetime
from pydantic import PastDatetime
from pydantic import UUID4

from app.core.fields import RequiredStr
from app.core.fields import TimedeltaSeconds


class OAuthToken(BaseModel):
    """Represent an OAuth token.

    Attributes
    ----------
    access_token : str
        The token used to access protected resources.
    id_token : str
        The token that contains identity information about the user.
    refresh_token : str
        The token used to obtain new access tokens after the current one expires.
    token_type : str
        The type of token, typically "bearer".
    expires_in : timedelta
        The time duration after which the token expires.
    scope : str
        The scope of the access granted by the token.

    """

    access_token: str
    id_token: str
    refresh_token: str
    token_type: str
    expires_in: TimedeltaSeconds
    scope: str


class BaseTokenPayload(BaseModel):
    """Base class representing the payload of a JWT token.

    Attributes
    ----------
    iss : str
        The issuer of the token.
    sub : str
        The subject or user identifier the token refers to.
    aud : list of str
        The audience for whom the token is intended.
    exp : FutureDatetime
        The expiration time of the token.
    nbf : PastDatetime
        The time before which the token must not be accepted for processing.
    jti: str
        The JWT token identifier.

    Notes
    -----
    This class is expected to be inherited from.

    """

    iss: str
    sub: str
    aud: list[str]
    exp: FutureDatetime
    nbf: PastDatetime
    jti: str

    @classmethod
    async def from_jwt(cls, token: str) -> Self:
        """Decode a JWT token and returns an instance of `BaseTokenPayload`."""
        raise NotImplementedError(".from_jwt() must be overridden.")


class BaseUser(BaseModel):
    """Base class representing a user.

    Attributes
    ----------
    id : UUID4
        The unique identifier of the user.
    username : str
        The username of the user. Must be at least 1 character long.
    email : EmailStr, optional
        The email address of the user.
    first_name : str, optional
        The first name of the user.
    last_name : str, optional
        The last name of the user.
    is_admin : bool, optional
        Whether the user has administrative privileges. Defaults to False.
    created_time : datetime, optional
        The datetime when the user was created. Defaults to current datetime.
    updated_time : datetime, optional
        The datetime when the user was last updated. Defaults to current datetime.
    full_name
    is_active

    Notes
    -----
    This class is expected to be inherited from.

    """

    id: UUID4
    username: RequiredStr
    email: EmailStr | Literal[""] = ""
    first_name: str = ""
    last_name: str = ""
    is_admin: bool = False
    created_time: datetime | None = datetime.now(tz=UTC)
    updated_time: datetime | None = datetime.now(tz=UTC)
    _access_token: str = ""

    @field_validator("created_time", "updated_time", mode="before")
    @classmethod
    def falsy_to_none(cls, v: str) -> str:
        """Convert falsy datetime strings to `None`.

        Parameters
        ----------
        v : Any
            The value to validate and potentially convert.

        Returns
        -------
        Any
            The original value if truthy, otherwise `None`.

        """
        if not v:
            return None
        return v

    @computed_field
    @property
    def full_name(self) -> str:
        """The combination of the user's first and last names."""
        return f"{self.first_name} {self.last_name}".strip()

    @computed_field
    @cached_property
    def is_active(self) -> bool:
        """Indicate whether the user is currently active."""
        return True

    @property
    def access_token(self) -> str:
        """Get the user's access token."""
        return self._access_token

    @access_token.setter
    def access_token(self, v: str) -> None:
        """Set the user's access token."""
        self._access_token = v

    @staticmethod
    async def get_oauth_token(
        code: str | None = None,
        username: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
    ) -> OAuthToken:
        """Obtain an OAuth token.

        This method must be overridden in subclasses to provide specific logic for
        obtaining OAuth tokens based on different grant types.

        Parameters
        ----------
        code : str, optional
            The authorization code received from the OAuth2 provider via redirect URL.
        username : str, optional
            The username for resource owner password credentials grant.
        password : str, optional
            The password for resource owner password credentials grant.
        refresh_token : str, optional
            The refresh token to obtain a new access token.

        Returns
        -------
        OAuthToken
            The OAuth token response.

        Raises
        ------
        NotImplementedError
            If the method is not overridden in a subclass.

        """
        raise NotImplementedError(".get_oauth_token() must be overridden.")

    @staticmethod
    async def invalidate_oauth_token(access_token: str) -> None:
        """Invalidate an OAuth token.

        This method must be overridden in subclasses to provide specific logic for
        invalidating OAuth tokens.

        Parameters
        ----------
        access_token : str
            The access token to invalidate.

        Raises
        ------
        NotImplementedError
            If the method is not overridden in a subclass.

        """
        raise NotImplementedError(".invalidate_oauth_token() must be overridden.")

    @classmethod
    async def get_user(cls, username: RequiredStr) -> Self:
        """Retrieve a user by username.

        This method must be overridden in subclasses to provide specific logic for
        retrieving a user from the data store.

        Parameters
        ----------
        username : RequiredStr
            The username of the user to retrieve.

        Returns
        -------
        Self
            An instance of the user model.

        Raises
        ------
        NotImplementedError
            If the method is not overridden in a subclass.

        """
        raise NotImplementedError(".get_user() must be overridden.")

    @classmethod
    async def get_users(cls) -> list[Self]:
        """Retrieve all users.

        This method must be overridden in subclasses to provide specific logic for
        retrieving all users from the data store.

        Returns
        -------
        list[Self]
            A list of user instances.

        Raises
        ------
        NotImplementedError
            If the method is not overridden in a subclass.

        """
        raise NotImplementedError(".get_users() must be overridden.")

    @classmethod
    async def from_token_payload(cls, token_payload: BaseTokenPayload) -> Self:
        """Create a user instance from a token payload.

        This method must be overridden in subclasses to provide specific logic for
        constructing a user instance based on the contents of a JWT token payload.

        Parameters
        ----------
        token_payload : BaseTokenPayload
            The decoded JWT token payload.

        Returns
        -------
        Self
            An instance of the user model.

        Raises
        ------
        NotImplementedError
            If the method is not overridden in a subclass.

        """
        raise NotImplementedError(".from_token_payload() must be overridden.")

    @classmethod
    async def from_jwt(cls, token: str) -> Self:
        """Create a user instance from a JWT token.

        This method must be overridden in subclasses to provide specific logic for
        decoding a JWT token and constructing a user instance.

        Parameters
        ----------
        token : str
            The JWT token string to decode.

        Returns
        -------
        Self
            An instance of the user model.

        Raises
        ------
        NotImplementedError
            If the method is not overridden in a subclass.

        """
        raise NotImplementedError(".from_jwt() must be overridden.")

    @classmethod
    async def from_code(cls, code: str) -> Self:
        """Create a user instance from an authorization code.

        This method must be overridden in subclasses to provide specific logic for
        exchanging an authorization code for user information and constructing a user
        instance.

        Parameters
        ----------
        code : str
            The authorization code received from the OAuth2 provider.

        Returns
        -------
        Self
            An instance of the user model.

        Raises
        ------
        NotImplementedError
            If the method is not overridden in a subclass.

        """
        raise NotImplementedError(".from_code() must be overridden.")

    @classmethod
    async def from_password(cls, username: str, password: str) -> Self:
        """Create a user instance from username and password.

        This method must be overridden in subclasses to provide specific logic for
        authenticating a user with a username and password and constructing a user
        instance.

        Parameters
        ----------
        username : str
            The username of the user.
        password : str
            The password of the user.

        Returns
        -------
        Self
            An instance of the user model.

        Raises
        ------
        NotImplementedError
            If the method is not overridden in a subclass.

        """
        raise NotImplementedError(".from_password() must be overridden.")
