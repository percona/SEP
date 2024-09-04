"""Define the app models."""

from typing import Annotated
from typing import Literal
from typing import Self

from pydantic import AliasChoices
from pydantic import computed_field
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic.alias_generators import to_camel

from app.core.auth.models import BaseTokenPayload
from app.core.auth.models import BaseUser
from app.core.auth.models import OAuthToken
from app.core.config import settings

casdoor_sdk = settings.CASDOOR.SDK

CasdoorUsernameField = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("username", "name"),
        pattern=r"^[a-zA-Z0-9]+(?:[_-][a-zA-Z0-9]+)*$",
    ),
]


class CasdoorTokenPayload(BaseTokenPayload):
    """Represent the payload of a Casdoor JWT token.

    Attributes
    ----------
    iss
    sub
    aud
    exp
    nbf
    username: CasdoorUsernameField
        The user's Casdoor username.
    active: bool
        Whether the token is active or not. Must be True.

    """

    username: CasdoorUsernameField
    active: Literal[True] = True

    @field_validator("iss")
    @classmethod
    def validate_iss(cls, v: str) -> str:
        """Validate if the token's iss is the same as `settings.CASDOOR.ENDPOINT`."""
        if v not in settings.CASDOOR.ALLOWED_ISSUERS:
            raise ValueError(f"Unknown token issuer: {v}")
        return v

    @field_validator("aud")
    @classmethod
    def validate_aud(cls, v: list[str]) -> list[str]:
        """Validate if `settings.CASDOOR.CLIENT_ID` is part of the token's audience."""
        if settings.CASDOOR.CLIENT_ID not in v:
            raise ValueError(f"Client ID not part of audience: {v}")
        return v

    @classmethod
    async def from_jwt(cls, token: str) -> Self:
        """Decode a JWT token and return an instance of `CasdoorTokenPayload`.

        Decode and validate a JWT access token and return an instance
        of `CasdoorTokenPayload`.

        Parameters
        ----------
        token : str
            The JWT token to decode.

        Returns
        -------
        CasdoorTokenPayload
            An instance of `CasdoorTokenPayload` populated with the decoded data.

        """
        async with casdoor_sdk._session as session:
            data = {"token": token, "token_type_hint": "access_token"}
            headers = {"Authorization": casdoor_sdk.headers["Authorization"]}
            token_data = await session.post(
                "/api/login/oauth/introspect",
                data=data,
                headers=headers,
            )
            return cls(**token_data)


class CasdoorUser(BaseUser):
    """Base class representing a user.

    Attributes
    ----------
    id
    username
    email
    first_name
    last_name
    is_admin
    created_time
    updated_time
    full_name
    is_active
    username: CasdoorUsernameField
        The user's Casdoor username.
    owner: str
        The user's Casdoor organization.
    is_forbidden: bool
        Whether the user has the `is_forbidden` attribute set in Casdoor.
        Defaults to False.
    is_deleted: bool
        Whether the user has the `is_deleted` attribute set in Casdoor.
        Defaults to False.

    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    username: CasdoorUsernameField
    owner: str
    is_forbidden: bool = False
    is_deleted: bool = False

    @computed_field
    @property
    def is_active(self) -> bool:
        """Return True if the user is not forbidden nor deleted."""
        return not self.is_forbidden and not self.is_deleted

    @staticmethod
    async def get_oauth_token(
        code: str | None = None,
        username: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
    ) -> OAuthToken:
        """Retrieve an OAuth token for the user.

        Get an OAuth token for the user from Casdoor's SDK. Either `code`,
        `refresh_token`, or `username` and `password` must be set.

        Parameters
        ----------
        code : str, optional
            An authorization code used to obtain the token.
        username : str, optional
            The username of the user.
        password : str, optional
            The password of the user.
        refresh_token : str, optional
            A refresh token used to obtain a new access token.

        Returns
        -------
        OAuthToken
            The OAuth token for the user.

        """
        if refresh_token:
            oauth_data = await casdoor_sdk.refresh_token_request(refresh_token)
        else:
            oauth_data = await casdoor_sdk.get_oauth_token(code, username, password)
        return OAuthToken(**oauth_data)

    @classmethod
    async def get_user(cls, username: CasdoorUsernameField) -> Self:
        """Get user by username.

        Parameters
        ----------
        username: CasdoorUsernameField
            The username of the user.

        Returns
        -------
        CasdoorUser
            An instance of `CasdoorUser`.

        """
        user_data = await casdoor_sdk.get_user(username)
        return cls(**user_data)

    @classmethod
    async def get_users(cls) -> list[Self]:
        """Get user list.

        Returns
        -------
        list of CasdoorUser
            The list of users.

        """
        users_data = await casdoor_sdk.get_users()
        return [cls(**user_data) for user_data in users_data]

    @classmethod
    async def from_token_payload(cls, token_payload: CasdoorTokenPayload) -> Self:
        """Create an instance of `CasdoorUser` from a `CasdoorTokenPayload`.

        Parameters
        ----------
        token_payload : CasdoorTokenPayload
            The Casdoor token payload containing user information.

        Returns
        -------
        CasdoorUser
            An instance of `CasdoorUser`.

        """
        return await cls.get_user(token_payload.username)

    @classmethod
    async def from_jwt(cls, token: str) -> Self:
        """Create an instance of `CasdoorUser` from a JWT token.

        Parameters
        ----------
        token : str
            The JWT token containing user information.

        Returns
        -------
        CasdoorUser
            An instance of `CasdoorUser`.

        """
        token_payload = await CasdoorTokenPayload.from_jwt(token)
        user = await cls.from_token_payload(token_payload)
        user._access_token = token
        return user

    @classmethod
    async def from_code(cls, code: str) -> Self:
        """Create an instance of `CasdoorUser` from an authorization code.

        Parameters
        ----------
        code : str
            The authorization code used to obtain user information.

        Returns
        -------
        CasdoorUser
            An instance of `CasdoorUser`.

        """
        oauth_token = await cls.authenticate(code)
        return await cls.from_jwt(oauth_token.access_token)

    @classmethod
    async def from_password(cls, username: str, password: str) -> Self:
        """Create an instance of `CasdoorUser` from a username and password.

        Parameters
        ----------
        username : str
            The username of the user.
        password : str
            The password of the user.

        Returns
        -------
        CasdoorUser
            An instance of `CasdoorUser`.

        """
        oauth_token = await cls.authenticate(username=username, password=password)
        return await cls.from_jwt(oauth_token.access_token)
