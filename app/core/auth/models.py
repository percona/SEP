"""Define the base auth models."""

from abc import ABC, abstractmethod
from datetime import datetime
from functools import cached_property
from typing import Literal, Self

from pydantic import (
    BaseModel,
    computed_field,
    EmailStr,
    Field,
    FutureDatetime,
    PastDatetime,
    UUID4,
)

from app.core.utils.date_time import utc_now
from app.core.utils.fields import EmptyStrToNone, RequiredStr, TimedeltaSeconds


class OAuthToken(BaseModel):
    """Represent an OAuth token.

    :param access_token: The token used to access protected resources.
    :type access_token: str
    :param id_token: The token that contains identity information about the user.
    :type id_token: str
    :param refresh_token: The token used to obtain new access tokens after the
        current one expires.
    :type refresh_token: str
    :param token_type: The type of token, typically "bearer".
    :type token_type: str
    :param expires_in: The time duration after which the token expires.
    :type expires_in: TimedeltaSeconds
    :param scope: The scope of the access granted by the token.
    :type scope: str
    """

    access_token: str
    id_token: str
    refresh_token: str
    token_type: str
    expires_in: TimedeltaSeconds
    scope: str


class BaseTokenPayload(BaseModel, ABC):
    """Base abstract class representing the payload of a JWT token.

    :param iss: The issuer of the token.
    :type iss: str
    :param sub: The subject or user identifier the token refers to.
    :type sub: str
    :param aud: The audience for whom the token is intended.
    :type aud: list[str]
    :param exp: The expiration time of the token.
    :type exp: FutureDatetime
    :param nbf: The time before which the token must not be accepted for
        processing.
    :type nbf: PastDatetime
    :param jti: The JWT token identifier.
    :type jti: str
    """

    iss: str
    sub: str
    aud: list[str]
    exp: FutureDatetime
    nbf: PastDatetime
    jti: str

    @classmethod
    @abstractmethod
    async def from_jwt(cls, token: str) -> Self:
        """Create an instance from a JWT token.

        :param token: The JWT token string to decode.
        :type token: str
        :return: An instance of the token payload.
        :rtype: Self
        """


class BaseUser(BaseModel, ABC):
    """Base abstract class for a user.

    :param id: The unique identifier of the user.
    :type id: UUID4
    :param username: The username of the user. Must be at least 1 character long.
    :type username: RequiredStr
    :param email: The email address of the user.
    :type email: EmailStr | Literal[""]
    :param first_name: The first name of the user.
    :type first_name: str
    :param last_name: The last name of the user.
    :type last_name: str
    :param is_admin: Whether the user has administrative privileges. Defaults
        to False.
    :type is_admin: bool
    :param created_time: The datetime when the user was created. Defaults to
        current datetime.
    :type created_time: datetime | None
    :param updated_time: The datetime when the user was last updated. Defaults
        to current datetime.
    :type updated_time: datetime | None
    """

    id: UUID4
    username: RequiredStr
    email: EmailStr | Literal[""] = ""
    first_name: str = ""
    last_name: str = ""
    is_admin: bool = False
    created_time: datetime | EmptyStrToNone = Field(default_factory=utc_now)
    updated_time: datetime | EmptyStrToNone = Field(default_factory=utc_now)
    _access_token: str = ""

    @computed_field
    @property
    def full_name(self) -> str:
        """The combination of the user's first and last names.

        :return: The user's full name.
        :rtype: str
        """
        return f"{self.first_name} {self.last_name}".strip()

    @computed_field
    @cached_property
    def is_active(self) -> bool:
        """Indicate whether the user is currently active.

        :return: True if the user is active, False otherwise.
        :rtype: bool
        """
        return True

    @property
    def access_token(self) -> str:
        """Get the user's access token.

        :return: The user's access token.
        :rtype: str
        """
        return self._access_token

    @access_token.setter
    def access_token(self, v: str) -> None:
        """Set the user's access token.

        :param v: The new access token.
        :type v: str
        """
        self._access_token = v

    @staticmethod
    @abstractmethod
    async def get_oauth_token(
        code: str | None = None,
        username: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
    ) -> OAuthToken:
        """Obtain an OAuth token.

        This method must be overridden in subclasses to provide specific logic for
        obtaining OAuth tokens based on different grant types.

        :param code: The authorization code received from the OAuth2 provider via
            redirect URL.
        :type code: str | None
        :param username: The username for resource owner password credentials grant.
        :type username: str | None
        :param password: The password for resource owner password credentials grant.
        :type password: str | None
        :param refresh_token: The refresh token to obtain a new access token.
        :type refresh_token: str | None
        :return: The OAuth token response.
        :rtype: OAuthToken
        """

    @staticmethod
    @abstractmethod
    async def invalidate_oauth_token(access_token: str) -> None:
        """Invalidate an OAuth token.

        This method must be overridden in subclasses to provide specific logic for
        invalidating OAuth tokens.

        :param access_token: The access token to invalidate.
        :type access_token: str
        """

    @classmethod
    @abstractmethod
    async def get_user(cls, username: RequiredStr) -> Self:
        """Retrieve a user by username.

        This method must be overridden in subclasses to provide specific logic for
        retrieving a user from the data store.

        :param username: The username of the user to retrieve.
        :type username: RequiredStr
        :return: An instance of the user model.
        :rtype: Self
        """

    @classmethod
    @abstractmethod
    async def get_users(cls) -> list[Self]:
        """Retrieve all users.

        This method must be overridden in subclasses to provide specific logic for
        retrieving all users from the data store.

        :return: A list of user instances.
        :rtype: list[Self]
        """

    @classmethod
    @abstractmethod
    async def from_token_payload(cls, token_payload: BaseTokenPayload) -> Self:
        """Create a user instance from a token payload.

        This method must be overridden in subclasses to provide specific logic for
        constructing a user instance based on the contents of a JWT token payload.

        :param token_payload: The decoded JWT token payload.
        :type token_payload: BaseTokenPayload
        :return: An instance of the user model.
        :rtype: Self
        """

    @classmethod
    @abstractmethod
    async def from_jwt(cls, token: str) -> Self:
        """Create a user instance from a JWT token.

        This method must be overridden in subclasses to provide specific logic for
        decoding a JWT token and constructing a user instance.

        :param token: The JWT token string to decode.
        :type token: str
        :return: An instance of the user model.
        :rtype: Self
        """

    @classmethod
    @abstractmethod
    async def from_code(cls, code: str) -> Self:
        """Create a user instance from an authorization code.

        This method must be overridden in subclasses to provide specific logic for
        exchanging an authorization code for user information and constructing a user
        instance.

        :param code: The authorization code received from the OAuth2 provider.
        :type code: str
        :return: An instance of the user model.
        :rtype: Self
        """

    @classmethod
    @abstractmethod
    async def from_password(cls, username: str, password: str) -> Self:
        """Create a user instance from username and password.

        This method must be overridden in subclasses to provide specific logic for
        authenticating a user with a username and password and constructing a user
        instance.

        :param username: The username of the user.
        :type username: str
        :param password: The password of the user.
        :type password: str
        :return: An instance of the user model.
        :rtype: Self
        """
