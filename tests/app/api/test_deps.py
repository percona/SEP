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

"""Define tests for the app.api.deps module."""

from datetime import timedelta

import pytest
from pydantic import SecretStr

from app.api.deps import get_current_admin, get_current_user, SERVICE_PRINCIPAL_ID
from app.core.auth.exceptions import HTTPForbiddenException, HTTPUnauthorizedException
from app.core.auth.providers.grafana.models import GrafanaUser
from app.core.auth.utils import get_user_model
from app.core.config import settings

User = get_user_model()


@pytest.mark.asyncio
async def test_get_current_user_valid_token(casdoor_mock, valid_username):
    """Test get_current_user returns user for a valid token."""
    token = "valid_token"
    user = await get_current_user(token)
    assert user.username == valid_username
    assert user.is_active


@pytest.mark.asyncio
async def test_get_current_user_invalid_token(casdoor_mock, mocker):
    """Test get_current_user raises HTTPUnauthorizedException for an invalid token."""
    token = "invalid_token"
    casdoor_mock.get_user.return_value = {}
    with pytest.raises(HTTPUnauthorizedException):
        await get_current_user(token)


@pytest.mark.asyncio
async def test_get_current_user_inactive_user(casdoor_mock, mocker):
    """Test get_current_user raises HTTPForbiddenException if user is inactive."""
    token = "valid_token"
    user = await User.from_jwt(token)
    user.is_forbidden = True
    mocker.patch("app.api.deps.User.from_jwt", return_value=user)
    with pytest.raises(HTTPForbiddenException):
        await get_current_user(token)


@pytest.mark.asyncio
async def test_get_current_user_internal_token_match(casdoor_mock, mocker):
    """Test get_current_user returns the service principal when the token matches."""
    secret = "supersecret"
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(secret))
    user = await get_current_user(secret)
    assert user.username == "sep-service"
    assert user.is_admin is False
    assert user.access_token == secret
    assert user.id == SERVICE_PRINCIPAL_ID
    casdoor_mock.introspect_token.assert_not_called()


@pytest.mark.asyncio
async def test_get_current_user_internal_token_mismatch_falls_through(
    casdoor_mock, valid_username, mocker
):
    """Test get_current_user falls through to Casdoor when the token does not match."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr("supersecret"))
    user = await get_current_user("not-the-secret")
    assert user.username == valid_username


@pytest.mark.asyncio
async def test_get_current_user_internal_token_unset_falls_through(
    casdoor_mock, valid_username, mocker
):
    """Test get_current_user uses Casdoor when SEP_INTERNAL_TOKEN is None."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", None)
    user = await get_current_user("supersecret")
    assert user.username == valid_username


@pytest.mark.asyncio
async def test_get_current_user_internal_token_empty_falls_through(
    casdoor_mock, valid_username, mocker
):
    """Test get_current_user falls through when SEP_INTERNAL_TOKEN is empty.

    An empty configured secret must not match an empty Bearer token; the
    request must continue down the Casdoor path.
    """
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(""))
    user = await get_current_user("")
    assert user.username == valid_username


@pytest.mark.asyncio
async def test_get_current_user_internal_token_trailing_whitespace_mismatch(
    casdoor_mock, valid_username, mocker
):
    """Test get_current_user rejects tokens that differ only by trailing whitespace."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr("supersecret"))
    user = await get_current_user("supersecret ")
    assert user.username == valid_username


@pytest.mark.asyncio
async def test_get_current_admin_valid_admin(casdoor_mock, valid_username):
    """Test get_current_admin returns the user if they are admin."""
    token = "valid_admin_token"
    user = await get_current_user(token)
    user.is_admin = True
    admin_user = await get_current_admin(user)
    assert admin_user == user
    assert admin_user.is_admin


@pytest.mark.asyncio
async def test_get_current_admin_non_admin_user(casdoor_mock, valid_username):
    """Test get_current_admin raises HTTPForbiddenException if user is not an admin."""
    token = "valid_non_admin_token"
    user = await get_current_user(token)
    user.is_admin = False
    with pytest.raises(HTTPForbiddenException):
        await get_current_admin(user)


class TestGetCurrentUserBearerTypes:
    """Verify which assertion types authenticate on the API Bearer surface.

    ``app.api.deps.User`` is bound at import time, so ``grafana_mock`` -- which
    patches the active-provider lookup -- does not rebind it; each test patches
    the module attribute so the real ``GrafanaUser`` runs.
    """

    @pytest.fixture(autouse=True)
    def _grafana_user_model(self, grafana_mock, mocker):
        """Point ``app.api.deps.User`` at the real Grafana user model."""
        mocker.patch("app.api.deps.User", GrafanaUser)

    @pytest.mark.asyncio
    async def test_accepts_an_access_assertion(self, grafana_user_record):
        """Verify the existing Bearer credential still authenticates."""
        oauth = await GrafanaUser.get_oauth_token(username="alice", password="secret")

        user = await get_current_user(oauth.access_token)

        assert user.username == grafana_user_record["login"]

    @pytest.mark.asyncio
    async def test_accepts_an_exchange_assertion(self, grafana_user_record):
        """Verify a session-exchange assertion authenticates an API call."""
        exchange = await GrafanaUser.exchange_token_from_session("ambient")

        user = await get_current_user(exchange.access_token)

        assert user.username == grafana_user_record["login"]

    @pytest.mark.asyncio
    async def test_rejects_a_refresh_assertion(self):
        """Verify a refresh assertion is refused on the Bearer surface."""
        oauth = await GrafanaUser.get_oauth_token(username="alice", password="secret")

        with pytest.raises(HTTPUnauthorizedException):
            await get_current_user(oauth.refresh_token)

    @pytest.mark.asyncio
    async def test_rejects_an_expired_exchange_assertion(self, grafana_mock, mocker):
        """Verify an exchange assertion past its own lifetime is refused."""
        exchange = await GrafanaUser.exchange_token_from_session("ambient")
        mocker.patch.object(
            grafana_mock, "exchange_token_max_age", timedelta(seconds=-1)
        )

        with pytest.raises(HTTPUnauthorizedException):
            await get_current_user(exchange.access_token)

    @pytest.mark.asyncio
    async def test_grafana_admin_reaches_an_admin_gated_surface(self, grafana_mock):
        """Verify a PMM Admin is no longer flattened to a non-admin principal.

        This is what the nginx-injected ``SEP_INTERNAL_TOKEN`` cannot provide:
        its service principal hardcodes ``is_admin`` false, so every admin-gated
        surface 403s for a real PMM Admin.
        """
        grafana_mock.get_current_user_orgs.return_value = [
            {"orgId": 1, "name": "Main Org.", "role": "Admin"}
        ]
        exchange = await GrafanaUser.exchange_token_from_session("ambient")

        user = await get_current_admin(await get_current_user(exchange.access_token))

        assert user.is_admin is True

    @pytest.mark.parametrize("role", ["Editor", "Viewer"])
    @pytest.mark.asyncio
    async def test_non_admin_roles_do_not_gain_admin(self, grafana_mock, role):
        """Verify a non-admin Grafana role stays non-admin through the exchange."""
        grafana_mock.get_current_user_orgs.return_value = [
            {"orgId": 1, "name": "Main Org.", "role": role}
        ]
        exchange = await GrafanaUser.exchange_token_from_session("ambient")

        user = await get_current_user(exchange.access_token)

        assert user.is_admin is False
        with pytest.raises(HTTPForbiddenException):
            await get_current_admin(user)

    @pytest.mark.asyncio
    async def test_internal_token_still_short_circuits_first(self, mocker):
        """Verify ``SEP_INTERNAL_TOKEN`` is matched before the assertion validator.

        The short-circuit must stay ahead of the Bearer validation, or every
        internal service-to-service call 401s.
        """
        secret = "supersecret"
        mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(secret))
        from_bearer = mocker.patch.object(GrafanaUser, "from_bearer")

        user = await get_current_user(secret)

        assert user.username == "sep-service"
        assert user.is_admin is False
        assert user.id == SERVICE_PRINCIPAL_ID
        from_bearer.assert_not_called()
