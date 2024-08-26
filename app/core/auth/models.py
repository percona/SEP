"""Define the base auth models."""

from datetime import datetime
from datetime import timedelta
from datetime import UTC
from functools import cached_property
from typing import Literal
from typing import Self

import jwt
from pydantic import BaseModel
from pydantic import computed_field
from pydantic import EmailStr
from pydantic import Field
from pydantic import field_validator
from pydantic import FutureDatetime
from pydantic import PastDatetime
from pydantic import UUID4

from app.core.config import settings


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
    # TODO: expires_in should be serialized as int
    expires_in: timedelta
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

    Notes
    -----
    This class is expected to be inherited from.

    """

    iss: str
    sub: str
    aud: list[str]
    exp: FutureDatetime
    nbf: PastDatetime

    @classmethod
    async def from_jwt(cls, token: str) -> Self:
        """Decode a JWT token and returns an instance of `BaseTokenPayload`.

        Parameters
        ----------
        token : str
            The JWT token to decode.

        Returns
        -------
        BaseTokenPayload
            An instance of `BaseTokenPayload` populated with the decoded data.

        """
        data = jwt.decode(
            token,
            settings.PUBLIC_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return cls(**data)

    def to_jwt(self) -> str:
        """Encode the current instance into a JWT token string.

        Returns
        -------
        str
            The encoded JWT token as a string.

        """
        return jwt.encode(
            self.model_dump(),
            settings.PRIVATE_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )


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
    username: str = Field(min_length=1)
    email: EmailStr | Literal[""] = ""
    first_name: str = ""
    last_name: str = ""
    is_admin: bool = False
    created_time: datetime | None = datetime.now(tz=UTC)
    updated_time: datetime | None = datetime.now(tz=UTC)

    @field_validator("created_time", "updated_time", mode="before")
    @classmethod
    def falsy_to_none(cls, v: str):
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

    @staticmethod
    async def get_oauth_token(
        code: str | None = None,
        username: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
    ) -> OAuthToken:
        raise NotImplementedError(".get_oauth_token() must be overridden.")

    @classmethod
    async def from_token_payload(cls, token_payload: BaseTokenPayload) -> Self:
        raise NotImplementedError(".from_token_payload() must be overridden.")

    @classmethod
    async def from_jwt(cls, token: str) -> Self:
        raise NotImplementedError(".from_token() must be overridden.")

    @classmethod
    async def from_code(cls, code: str) -> Self:
        raise NotImplementedError(".from_code() must be overridden.")

    @classmethod
    async def from_password(cls, username: str, password: str) -> Self:
        raise NotImplementedError(".from_password() must be overridden.")
