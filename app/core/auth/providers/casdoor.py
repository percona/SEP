"""Provide the CasdoorSDK for interacting with Casdoor services."""

from base64 import b64encode
from typing import Any
from typing import Literal
from typing import Self

from pydantic import model_validator

from app.core.config import settings
from app.core.requests import RemoteAPI


class CasdoorSDK(RemoteAPI):
    """Interact with Casdoor's authentication and user management APIs.

    The `CasdoorSDK` class extends `RemoteAPI` to provide methods for managing OAuth
    tokens and retrieving user information from Casdoor. It handles authentication
    using client credentials and supports various grant types for obtaining access
    tokens.

    Attributes
    ----------
    auth_scheme : str, optional
        The authentication scheme to use (default is "Basic").
    client_id : str
        The client ID for Casdoor authentication.
    client_secret : str
        The client secret for Casdoor authentication.
    org_name : str
        The organization name in Casdoor.

    """

    auth_scheme: str = "Basic"
    client_id: str
    client_secret: str
    org_name: str

    @model_validator(mode="after")
    def set_api_key_from_credentials(self) -> Self:
        """Set the API key by encoding client credentials.

        Encodes the `client_id` and `client_secret` into a Base64 string and sets it
        as the `api_key` for authentication.

        Returns
        -------
        Self
            The updated instance with the `api_key` set.

        """
        self.api_key = b64encode(
            f"{self.client_id}:{self.client_secret}".encode(),
        ).decode("utf-8")
        return self

    async def refresh_token_request(
        self,
        refresh_token: str,
        scope: str = "",
    ) -> dict[str, Any]:
        """Request a new access token using a refresh token.

        Sends a request to Casdoor to obtain a new access token using the provided
        refresh token and optional scope.

        Parameters
        ----------
        refresh_token : str
            The refresh token to send to Casdoor.
        scope : str, optional
            The OAuth scope for the token request (default is an empty string).

        Returns
        -------
        dict[str, Any]
            The response from Casdoor containing the new access token.

        """
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": scope,
            "refresh_token": refresh_token,
        }
        return await self.post("/api/login/oauth/refresh_token", json=data)

    async def get_access_token(
        self,
        code: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Obtain an OAuth access token from Casdoor.

        Requests an OAuth token from Casdoor using either an authorization code,
        username and password, or client credentials.

        Parameters
        ----------
        code : str, optional
            The authorization code received from Casdoor via redirect URL.
        username : str, optional
            The username for resource owner password credentials grant.
        password : str, optional
            The password for resource owner password credentials grant.

        Returns
        -------
        dict[str, Any]
            The OAuth token response from Casdoor.

        """
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if code:
            data["code"] = code
            data["grant_type"] = "authorization_code"
        elif username and password:
            data["username"] = username
            data["password"] = password
            data["grant_type"] = "password"
        return await self.post("/api/login/oauth/access_token", json=data)

    async def introspect_token(
        self,
        token: str,
        token_type: Literal["access_token", "refresh_token"] = "access_token",  # noqa: S107
    ) -> dict[str, Any]:
        """Introspect a token to verify its validity.

        Sends a request to Casdoor to verify the provided token and its type.

        Parameters
        ----------
        token : str
            The token to introspect.
        token_type : Literal["access_token", "refresh_token"], optional
            The type of the token being introspected (default is "access_token").

        Returns
        -------
        dict[str, Any]
            The introspection result from Casdoor.

        """
        return await self.post(
            "/api/login/oauth/introspect",
            data={"token": token, "token_type_hint": token_type},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    async def get_token(self, token_id: str) -> dict[str, Any]:
        """Retrieve a specific token by its ID.

        Fetches the token details from Casdoor using the provided token ID.

        Parameters
        ----------
        token_id : str
            The ID of the token to retrieve.

        Returns
        -------
        dict[str, Any]
            The token details retrieved from Casdoor.

        """
        return await self.get("/api/get-token", params={"id": token_id})

    async def get_users(self) -> dict[str, Any]:
        """Retrieve a list of users from Casdoor.

        Fetches all users associated with the configured organization from Casdoor.

        Returns
        -------
        dict[str, Any]
            A dictionary containing a list of user information.

        """
        users = await self.get("/api/get-users", params={"owner": self.org_name})
        return users["data"]

    async def get_user(self, user_id: str) -> dict[str, Any]:
        """Retrieve a specific user's information from Casdoor.

        Fetches the details of a user identified by the provided user ID.

        Parameters
        ----------
        user_id : str
            The ID of the user to retrieve.

        Returns
        -------
        dict[str, Any]
            A dictionary containing the user's information.

        """
        user = await self.get(
            "/api/get-user",
            params={"id": f"{self.org_name}/{user_id}"},
        )
        return user["data"]


casdoor_sdk = CasdoorSDK(
    endpoint=settings.CASDOOR.ENDPOINT,
    client_id=settings.CASDOOR.CLIENT_ID,
    client_secret=settings.CASDOOR.CLIENT_SECRET,
    org_name=settings.CASDOOR.ORGANIZATION_NAME,
)
