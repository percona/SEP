# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Provide the GrafanaSDK for interacting with Grafana services."""

from datetime import timedelta
from typing import Annotated, Any

from aiohttp import ClientConnectionError
from annotated_types import Gt
from async_lru import _LRUCacheWrapper, alru_cache
from fastapi import status
from pydantic import ConfigDict, SecretStr

from app.core.auth.exceptions import (
    BaseAuthProviderException,
    HTTPUnauthorizedException,
)
from app.core.requests import as_json_array, as_json_object, RemoteAPI
from app.core.utils.fields import NonEmptyStr, TimedeltaSeconds


class GrafanaException(BaseAuthProviderException):
    """Define exception for Grafana connection errors.

    :param status_code: The HTTP status code for the error response. Defaults to
        502 (Bad Gateway).
    :param detail: A message providing additional details about the exception.
        Defaults to "Grafana error".
    """

    def __init__(
        self,
        status_code: int = status.HTTP_502_BAD_GATEWAY,
        detail: str = "Grafana error",
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)


class GrafanaSDK(RemoteAPI):
    """Interact with Grafana's authentication and user-management APIs.

    The ``GrafanaSDK`` class extends ``RemoteAPI`` to authenticate human logins
    against Grafana's password-login endpoint and to read user and org-user data
    with a service-account bearer token. It sets no default ``Authorization``
    header: the human-login flow authenticates via Grafana's session cookie,
    while the programmatic calls inject the service-account bearer per request.

    :param endpoint: The base URL for the Grafana API endpoint.
    :param verify_ssl: Whether to verify SSL certificates. Defaults to True.
    :param service_account_token: The Grafana service-account token used as a
        bearer credential for programmatic user reads.
    :param access_token_max_age: How long a minted access assertion stays valid
        (the per-request Bearer credential). Defaults to 1 hour.
    :param refresh_token_max_age: How long a minted refresh assertion stays valid
        (the SPA's ``HttpOnly`` refresh cookie). Defaults to 7 days.
    :param exchange_token_max_age: How long a minted session-exchange assertion
        stays valid (the embedded UI's in-memory bearer). Defaults to 5 minutes.
        This value alone bounds how long a signed-out browser keeps embedded
        access, and how long a Grafana role change takes to take effect, so it
        deliberately does not fall back to ``access_token_max_age``. A
        non-positive value expires every assertion at mint time and is rejected
        at config load rather than silently disabling embedded-UI auth.
    :param error_detail_key: The key Grafana uses for error details. Defaults to
        "message".
    :param session_cookie_name: The name of the cookie Grafana sets on a
        successful password login. Defaults to ``grafana_session``.
    """

    model_config = ConfigDict(ignored_types=(_LRUCacheWrapper,))
    logger_name: str = __name__
    service_account_token: SecretStr
    access_token_max_age: TimedeltaSeconds = timedelta(hours=1)
    refresh_token_max_age: TimedeltaSeconds = timedelta(days=7)
    exchange_token_max_age: Annotated[TimedeltaSeconds, Gt(timedelta(0))] = timedelta(
        minutes=5
    )
    error_detail_key: NonEmptyStr = "message"
    session_cookie_name: NonEmptyStr = "grafana_session"

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Perform an HTTP request and translate connection errors.

        :param method: The HTTP method to use for the request.
        :param path: The API endpoint path to request.
        :param kwargs: Additional keyword arguments to pass to the request.
        :return: The JSON response, or ``None`` on HTTP 204.
        :raises GrafanaException: If Grafana cannot be reached.
        """
        try:
            return await super().request(method, path, **kwargs)
        except ClientConnectionError:
            self.logger.exception("Failed to connect to Grafana.")
            raise GrafanaException(
                detail=f"Cannot connect to Grafana at {self.endpoint}"
            ) from None

    async def login(self, username: str, password: str) -> str:
        """Authenticate a user against Grafana and return the session cookie.

        Post the credentials to Grafana's JSON login endpoint and return the
        established session cookie value. The cookie is used only to read the
        logging-in user's identity and is never persisted.

        :param username: The Grafana username.
        :param password: The Grafana password.
        :return: The value of the established ``grafana_session`` cookie.
        :raises HTTPUnauthorizedException: If Grafana rejects the credentials
            (HTTP 401).
        :raises GrafanaException: If Grafana returns an unexpected status,
            establishes no session, or cannot be reached.
        """
        try:
            async with self._request(
                "POST",
                "/login",
                json={"user": username, "password": password},
            ) as response:
                if response.status == status.HTTP_401_UNAUTHORIZED:
                    raise HTTPUnauthorizedException("Invalid username or password")
                if response.status != status.HTTP_200_OK:
                    raise GrafanaException(
                        detail=f"Grafana login failed (HTTP {response.status})."
                    )
                session_cookie = response.cookies.get(self.session_cookie_name)
                if session_cookie is None:
                    raise GrafanaException(
                        detail="Grafana did not establish a session."
                    )
                return session_cookie.value
        except ClientConnectionError:
            self.logger.exception("Failed to connect to Grafana.")
            raise GrafanaException(
                detail=f"Cannot connect to Grafana at {self.endpoint}"
            ) from None

    async def get_current_user(self, session: str) -> dict[str, Any]:
        """Read the identity of the user owning ``session``.

        :param session: The ``grafana_session`` cookie value from :meth:`login`.
        :return: The Grafana ``/api/user`` record for the session's user.
        """
        with self.extra_headers({"Cookie": f"{self.session_cookie_name}={session}"}):
            return as_json_object(await self.get("/api/user"))

    async def get_current_user_orgs(self, session: str) -> list[dict[str, Any]]:
        """Read the org memberships of the user owning ``session``.

        :param session: The ``grafana_session`` cookie value from :meth:`login`.
        :return: The Grafana ``/api/user/orgs`` records for the session's user.
        """
        with self.extra_headers({"Cookie": f"{self.session_cookie_name}={session}"}):
            return as_json_array(await self.get("/api/user/orgs"))

    @alru_cache(ttl=300)
    async def get_org_users(self) -> list[dict[str, Any]]:
        """Read the org users via the service-account bearer token.

        :return: The Grafana ``/api/org/users`` records.
        """
        with self.auth(self.service_account_token.get_secret_value()):
            return as_json_array(await self.get("/api/org/users"))

    async def lookup_user(self, login: str) -> dict[str, Any]:
        """Fetch a single user by login or email via the service account.

        :param login: The login or email to look up.
        :return: The Grafana ``/api/users/lookup`` record for the user.
        """
        with self.auth(self.service_account_token.get_secret_value()):
            return as_json_object(
                await self.get("/api/users/lookup", params={"loginOrEmail": login})
            )
