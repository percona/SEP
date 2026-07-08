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

"""Define tests for the Grafana SDK."""

import logging
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientConnectionError

from app.core.auth.exceptions import HTTPUnauthorizedException
from app.core.auth.providers.grafana.sdk import GrafanaException, GrafanaSDK

_ENDPOINT = "https://grafana.example.com"
_SERVICE_TOKEN = "test-service-account-token"
_SESSION_VALUE = "grafana-session-cookie-value"


def _sdk() -> GrafanaSDK:
    """Build a ``GrafanaSDK`` with minimal config."""
    return GrafanaSDK(endpoint=_ENDPOINT, service_account_token=_SERVICE_TOKEN)


def _mock_response(*, status=200, json_data=None, cookies=None):
    """Build a mock aiohttp response usable as an async context manager."""
    response = AsyncMock()
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    response.status = status
    response.json = AsyncMock(return_value=json_data)
    response.raise_for_status = MagicMock()
    response.cookies = cookies if cookies is not None else SimpleCookie()
    return response


def _attach_session(sdk, response):
    """Attach a mock ``ClientSession`` returning ``response`` to ``sdk``."""
    session = MagicMock()
    session.request = MagicMock(return_value=response)
    sdk._session = session
    return session


def test_service_account_token_masked_in_repr():
    """Verify the service-account token is masked in repr."""
    assert _SERVICE_TOKEN not in repr(_sdk())


def test_headers_carry_no_default_authorization():
    """Verify the SDK sets no default ``Authorization`` header."""
    assert "Authorization" not in _sdk().headers


@pytest.mark.asyncio
async def test_login_returns_session_cookie():
    """Verify login posts credentials and returns the session cookie value."""
    sdk = _sdk()
    cookies = SimpleCookie()
    cookies["grafana_session"] = _SESSION_VALUE
    session = _attach_session(sdk, _mock_response(status=200, cookies=cookies))

    result = await sdk.login("alice", "secret")

    assert result == _SESSION_VALUE
    args, kwargs = session.request.call_args
    assert args[:2] == ("POST", "/login")
    assert kwargs["json"] == {"user": "alice", "password": "secret"}
    assert "Authorization" not in kwargs.get("headers", {})


@pytest.mark.asyncio
async def test_login_raises_unauthorized_on_bad_credentials():
    """Verify a 401 login response raises ``HTTPUnauthorizedException``."""
    sdk = _sdk()
    _attach_session(sdk, _mock_response(status=401))

    with pytest.raises(HTTPUnauthorizedException):
        await sdk.login("alice", "wrong")


@pytest.mark.asyncio
async def test_login_raises_grafana_error_on_upstream_failure():
    """Verify a non-401 error status surfaces as ``GrafanaException``, not a 401.

    A Grafana outage (5xx) or throttling (429) must not be reported to the user
    as bad credentials.
    """
    sdk = _sdk()
    _attach_session(sdk, _mock_response(status=500))

    with pytest.raises(GrafanaException, match="login failed"):
        await sdk.login("alice", "secret")


@pytest.mark.asyncio
async def test_login_does_not_log_password(caplog):
    """Verify the login password never reaches the debug request log."""
    sdk = _sdk()
    cookies = SimpleCookie()
    cookies["grafana_session"] = _SESSION_VALUE
    _attach_session(sdk, _mock_response(status=200, cookies=cookies))

    with caplog.at_level(logging.DEBUG, logger=sdk.logger_name):
        await sdk.login("alice", "super-secret-pw")

    assert "super-secret-pw" not in caplog.text
    assert "****" in caplog.text


@pytest.mark.asyncio
async def test_login_raises_when_no_session_established():
    """Verify a 200 login with no session cookie raises ``GrafanaException``."""
    sdk = _sdk()
    _attach_session(sdk, _mock_response(status=200, cookies=SimpleCookie()))

    with pytest.raises(GrafanaException, match="did not establish a session"):
        await sdk.login("alice", "secret")


@pytest.mark.asyncio
async def test_login_translates_connection_error():
    """Verify a connection error during login surfaces as ``GrafanaException``."""
    sdk = _sdk()
    session = MagicMock()
    session.request = MagicMock(side_effect=ClientConnectionError("down"))
    sdk._session = session

    with pytest.raises(GrafanaException, match="Cannot connect to Grafana"):
        await sdk.login("alice", "secret")


@pytest.mark.asyncio
async def test_get_current_user_sends_cookie_without_authorization():
    """Verify get_current_user authenticates via the session cookie only."""
    sdk = _sdk()
    record = {"id": 1, "login": "alice"}
    session = _attach_session(sdk, _mock_response(status=200, json_data=record))

    result = await sdk.get_current_user("sess-123")

    assert result == record
    headers = session.request.call_args.kwargs["headers"]
    assert headers["Cookie"] == "grafana_session=sess-123"
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_get_current_user_orgs_sends_cookie_without_authorization():
    """Verify get_current_user_orgs authenticates via the session cookie only."""
    sdk = _sdk()
    orgs = [{"orgId": 1, "role": "Admin"}]
    session = _attach_session(sdk, _mock_response(status=200, json_data=orgs))

    result = await sdk.get_current_user_orgs("sess-123")

    assert result == orgs
    headers = session.request.call_args.kwargs["headers"]
    assert headers["Cookie"] == "grafana_session=sess-123"
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_get_org_users_sends_service_account_bearer():
    """Verify get_org_users authenticates with the service-account bearer token."""
    GrafanaSDK.get_org_users.cache_clear()
    sdk = _sdk()
    session = _attach_session(sdk, _mock_response(status=200, json_data=[]))

    await sdk.get_org_users()

    headers = session.request.call_args.kwargs["headers"]
    assert headers["Authorization"] == f"Bearer {_SERVICE_TOKEN}"
    assert "Cookie" not in headers
    GrafanaSDK.get_org_users.cache_clear()


@pytest.mark.asyncio
async def test_lookup_user_sends_service_account_bearer():
    """Verify lookup_user sends the bearer token and the loginOrEmail param."""
    sdk = _sdk()
    session = _attach_session(
        sdk, _mock_response(status=200, json_data={"id": 7, "login": "bob"})
    )

    await sdk.lookup_user("bob")

    call = session.request.call_args
    assert call.kwargs["headers"]["Authorization"] == f"Bearer {_SERVICE_TOKEN}"
    assert call.kwargs["params"] == {"loginOrEmail": "bob"}


@pytest.mark.asyncio
async def test_get_org_users_is_cached(mocker):
    """Verify get_org_users caches its result (``@alru_cache``)."""
    GrafanaSDK.get_org_users.cache_clear()
    sdk = _sdk()
    get_mock = mocker.patch.object(
        GrafanaSDK, "get", new=mocker.AsyncMock(return_value=[])
    )

    await sdk.get_org_users()
    await sdk.get_org_users()

    assert get_mock.await_count == 1
    GrafanaSDK.get_org_users.cache_clear()


@pytest.mark.asyncio
async def test_request_translates_connection_error():
    """Verify a connection error on a request surfaces as ``GrafanaException``."""
    sdk = _sdk()
    session = MagicMock()
    session.request = MagicMock(side_effect=ClientConnectionError("down"))
    sdk._session = session

    with pytest.raises(GrafanaException, match="Cannot connect to Grafana"):
        await sdk.get("/api/user")
