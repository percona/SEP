"""Define the app models."""

from typing import Annotated, Literal, Self

from pydantic import AliasChoices, computed_field, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.core.auth.models import BaseTokenPayload, BaseUser, OAuthToken
from app.core.config import settings

CasdoorUsernameField = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("username", "name"),
        pattern=r"^[a-zA-Z0-9]+(?:[_-][a-zA-Z0-9]+)*$",
    ),
]


class CasdoorTokenPayload(BaseTokenPayload):
    """Represent the payload of a Casdoor JWT token.

    :param iss: The issuer of the token.
    :type iss: str
    :param sub: The subject or user identifier the token refers to.
    :type sub: str
    :param aud: The audience for whom the token is intended.
    :type aud: list[str]
    :param exp: The expiration time of the token.
    :type exp: FutureDatetime
    :param nbf: The time before which the token must not be accepted for processing.
    :type nbf: PastDatetime
    :param jti: The JWT token identifier.
    :type jti: str
    :param username: The user's Casdoor username.
    :type username: CasdoorUsernameField
    :param active: Whether the token is active or not. Must be True.
    :type active: bool
    """

    username: CasdoorUsernameField
    active: Literal[True] = True

    @field_validator("iss")
    @classmethod
    def validate_iss(cls, v: str) -> str:
        """Validate if the token's iss is the same as `settings.CASDOOR.endpoint`.

        :param v: The issuer value to validate.
        :type v: str
        :return: The validated issuer.
        :rtype: str
        """
        if (
            settings.CASDOOR.allowed_issuers != "*"
            and v not in settings.CASDOOR.allowed_issuers
        ):
            raise ValueError(f"Unknown token issuer: {v}")
        return v

    @field_validator("aud")
    @classmethod
    def validate_aud(cls, v: list[str]) -> list[str]:
        """Validate if `settings.CASDOOR.client_id` is part of the token's audience.

        :param v: The audience list to validate.
        :type v: list[str]
        :return: The validated audience list.
        :rtype: list[str]
        """
        if settings.CASDOOR.client_id not in v:
            raise ValueError(f"Client ID not part of audience: {v}")
        return v

    @classmethod
    async def from_jwt(cls, token: str) -> Self:
        """Decode a JWT token and return an instance of `CasdoorTokenPayload`.

        Decode and validate a JWT access token and return an instance
        of `CasdoorTokenPayload`.

        :param token: The JWT token to decode.
        :type token: str
        :return: An instance of `CasdoorTokenPayload` populated with the decoded data.
        :rtype: CasdoorTokenPayload
        """
        return cls.model_validate(await settings.CASDOOR.introspect_token(token))


class CasdoorUser(BaseUser):
    """Represent a Casdoor user.

    :param id: The unique identifier of the user.
    :type id: UUID4
    :param email: The email address of the user.
    :type email: EmailStr
    :param first_name: The first name of the user.
    :type first_name: str
    :param last_name: The last name of the user.
    :type last_name: str
    :param is_admin: Whether the user has administrative privileges. Defaults to False.
    :type is_admin: bool
    :param created_time: The datetime when the user was created. Defaults to current
        datetime.
    :type created_time: datetime | None
    :param updated_time: The datetime when the user was last updated. Defaults to
        current datetime.
    :type updated_time: datetime | None
    :param username: The user's Casdoor username.
    :type username: CasdoorUsernameField
    :param owner: The user's Casdoor organization.
    :type owner: str
    :param is_forbidden: Whether the user has the `is_forbidden` attribute set in
        Casdoor. Defaults to False.
    :type is_forbidden: bool
    :param is_deleted: Whether the user has the `is_deleted` attribute set in Casdoor.
        Defaults to False.
    :type is_deleted: bool
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    username: CasdoorUsernameField
    owner: str
    is_forbidden: bool = False
    is_deleted: bool = False

    @computed_field
    @property
    def is_active(self) -> bool:
        """Return True if the user is not forbidden nor deleted.

        :return: True if the user is active.
        :rtype: bool
        """
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

        :param code: An authorization code used to obtain the token.
        :type code: str | None
        :param username: The username of the user.
        :type username: str | None
        :param password: The password of the user.
        :type password: str | None
        :param refresh_token: A refresh token used to obtain a new access token.
        :type refresh_token: str | None
        :return: The OAuth token for the user.
        :rtype: OAuthToken
        """
        if refresh_token:
            oauth_data = await settings.CASDOOR.refresh_token_request(refresh_token)
        else:
            oauth_data = await settings.CASDOOR.get_access_token(
                code, username, password
            )
        return OAuthToken(**oauth_data)

    @staticmethod
    async def invalidate_oauth_token(access_token: str) -> None:
        """Invalidate an OAuth token.

        Invalidate an OAuth token by refreshing the token.

        :param access_token: The access token to invalidate.
        :type access_token: str
        """
        token_payload = await CasdoorTokenPayload.from_jwt(access_token)
        token_data = await settings.CASDOOR.get_token(token_payload.jti)
        await CasdoorUser.get_oauth_token(
            refresh_token=token_data["data"]["refreshToken"],
        )

    @classmethod
    async def get_user(cls, username: CasdoorUsernameField) -> Self:
        """Get user by username.

        :param username: The username of the user.
        :type username: CasdoorUsernameField
        :return: An instance of `CasdoorUser`.
        :rtype: CasdoorUser
        """
        user_data = await settings.CASDOOR.get_user(username)
        return cls(**user_data)

    @classmethod
    async def get_users(cls) -> list[Self]:
        """Get user list.

        :return: The list of users.
        :rtype: list[CasdoorUser]
        """
        users_data = await settings.CASDOOR.get_users()
        return [cls(**user_data) for user_data in users_data]

    @classmethod
    async def from_token_payload(cls, token_payload: CasdoorTokenPayload) -> Self:
        """Create an instance of `CasdoorUser` from a `CasdoorTokenPayload`.

        :param token_payload: The Casdoor token payload containing user information.
        :type token_payload: CasdoorTokenPayload
        :return: An instance of `CasdoorUser`.
        :rtype: CasdoorUser
        """
        return await cls.get_user(token_payload.username)

    @classmethod
    async def from_jwt(cls, token: str) -> Self:
        """Create an instance of `CasdoorUser` from a JWT token.

        :param token: The JWT token containing user information.
        :type token: str
        :return: An instance of `CasdoorUser`.
        :rtype: CasdoorUser
        """
        token_payload = await CasdoorTokenPayload.from_jwt(token)
        user = await cls.from_token_payload(token_payload)
        user.access_token = token
        return user

    @classmethod
    async def from_code(cls, code: str) -> Self:
        """Create an instance of `CasdoorUser` from an authorization code.

        :param code: The authorization code used to obtain user information.
        :type code: str
        :return: An instance of `CasdoorUser`.
        :rtype: CasdoorUser
        """
        oauth_token = await cls.get_oauth_token(code)
        return await cls.from_jwt(oauth_token.access_token)

    @classmethod
    async def from_password(cls, username: str, password: str) -> Self:
        """Create an instance of `CasdoorUser` from a username and password.

        :param username: The username of the user.
        :type username: str
        :param password: The password of the user.
        :type password: str
        :return: An instance of `CasdoorUser`.
        :rtype: CasdoorUser
        """
        oauth_token = await cls.get_oauth_token(username=username, password=password)
        return await cls.from_jwt(oauth_token.access_token)
