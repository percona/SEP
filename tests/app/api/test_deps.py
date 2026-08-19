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

from app.api.deps import (
    get_current_admin,
    get_current_user,
    require_admin_for_unsafe_methods,
    SERVICE_PRINCIPAL_ID,
)
from app.core.auth.exceptions import HTTPForbiddenException, HTTPUnauthorizedException
from app.core.auth.models import UserRole
from app.core.auth.providers.grafana.models import GrafanaUser
from app.core.auth.utils import get_user_model
from app.core.config import settings
from app.tasks.routes import latest_task_history
from tests.app.conftest import make_request, make_roleless_grafana_assertion

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
    user.role = UserRole.ADMIN
    admin_user = await get_current_admin(user)
    assert admin_user == user
    assert admin_user.is_admin


@pytest.mark.asyncio
async def test_get_current_admin_non_admin_user(casdoor_mock, valid_username):
    """Test get_current_admin raises HTTPForbiddenException if user is not an admin."""
    token = "valid_non_admin_token"
    user = await get_current_user(token)
    user.role = UserRole.VIEWER
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
    async def test_rejects_an_assertion_minted_before_the_role_claim(self):
        """Verify a legacy assertion is refused as a 401, not raised as a 500."""
        legacy = make_roleless_grafana_assertion("access")

        with pytest.raises(HTTPUnauthorizedException):
            await get_current_user(legacy)

    @pytest.mark.asyncio
    async def test_an_editor_resolves_to_the_editor_identity(
        self, grafana_mock, grafana_user_orgs
    ):
        """Verify the identity ``GET /api/users/me`` serves reports the real role.

        ``retrieve_current_user`` returns ``current_user`` untouched, so what
        ``get_current_user`` yields, and how it serializes, is exactly what that
        route would answer with.
        """
        grafana_mock.get_current_user_orgs.return_value = [
            {**grafana_user_orgs[0], "role": "Editor"}
        ]
        exchange = await GrafanaUser.exchange_token_from_session("ambient")

        user = await get_current_user(exchange.access_token)

        assert user.role is UserRole.EDITOR
        assert user.is_admin is False
        assert user.model_dump(mode="json", by_alias=True)["role"] == "editor"

    @pytest.mark.asyncio
    async def test_grafana_admin_reaches_an_admin_gated_surface(
        self, grafana_mock, grafana_user_orgs
    ):
        """Verify a PMM Admin is no longer flattened to a non-admin principal.

        This is what the nginx-injected ``SEP_INTERNAL_TOKEN`` cannot provide:
        its service principal hardcodes ``is_admin`` false, so every admin-gated
        surface 403s for a real PMM Admin.
        """
        grafana_mock.get_current_user_orgs.return_value = [
            {**grafana_user_orgs[0], "role": "Admin"}
        ]
        exchange = await GrafanaUser.exchange_token_from_session("ambient")

        user = await get_current_admin(await get_current_user(exchange.access_token))

        assert user.is_admin is True

    @pytest.mark.parametrize("role", ["Editor", "Viewer"])
    @pytest.mark.asyncio
    async def test_non_admin_roles_do_not_gain_admin(
        self, grafana_mock, grafana_user_orgs, role
    ):
        """Verify a non-admin Grafana role stays non-admin through the exchange."""
        grafana_mock.get_current_user_orgs.return_value = [
            {**grafana_user_orgs[0], "role": role}
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


class TestRequireAdminForUnsafeMethods:
    """Cover the router-level admin gate on mutating HTTP methods."""

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    @pytest.mark.asyncio
    async def test_safe_methods_pass_without_any_credential(self, method):
        """Verify a safe method returns without touching authentication.

        ``GET /health`` is unauthenticated on all three services, so the gate
        must not resolve a user before deciding a read is allowed.
        """
        assert await require_admin_for_unsafe_methods(make_request(method)) is None

    @pytest.mark.asyncio
    async def test_admin_passes_on_a_mutating_method(
        self, casdoor_mock, casdoor_user_data, mocker
    ):
        """Verify an admin's POST is admitted."""
        mocker.patch(
            "app.core.auth.providers.casdoor.sdk.CasdoorSDK.get_user",
            new=mocker.AsyncMock(return_value={**casdoor_user_data, "is_admin": True}),
        )
        request = make_request("POST", authorization="Bearer valid_token")

        assert await require_admin_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_non_admin_is_forbidden_on_a_mutating_method(self, casdoor_mock):
        """Verify a signed-in non-admin is refused with 403, not 401."""
        request = make_request("POST", authorization="Bearer valid_token")

        with pytest.raises(HTTPForbiddenException):
            await require_admin_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_missing_authorization_header_is_unauthorized(self):
        """Verify a credential-less mutation raises the project 401.

        The header is checked before ``oauth2_scheme``, which carries
        ``auto_error=True`` and would raise a bare Starlette ``HTTPException``.
        """
        with pytest.raises(HTTPUnauthorizedException):
            await require_admin_for_unsafe_methods(make_request("POST"))

    @pytest.mark.asyncio
    async def test_non_bearer_authorization_header_is_unauthorized(self):
        """Verify a non-Bearer credential is refused before token validation."""
        request = make_request("POST", authorization="Basic dXNlcjpwYXNz")

        with pytest.raises(HTTPUnauthorizedException):
            await require_admin_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_invalid_token_is_never_admitted(self, casdoor_mock, mocker):
        """Verify a Bearer credential that fails validation is refused."""
        mocker.patch(
            "app.core.auth.providers.casdoor.sdk.CasdoorSDK.introspect_token",
            new=mocker.AsyncMock(return_value={}),
        )
        request = make_request("POST", authorization="Bearer invalid_token")

        with pytest.raises(HTTPUnauthorizedException):
            await require_admin_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_service_principal_is_admitted_by_identity(self, mocker):
        """Verify ``SEP_INTERNAL_TOKEN``'s principal passes the gate.

        Scheduled inventory sync and scheduled execution authenticate with this
        token and write through the gated services.
        """
        secret = "supersecret"
        mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(secret))
        request = make_request("POST", authorization=f"Bearer {secret}")

        assert await require_admin_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_service_principal_gains_nothing_beyond_this_gate(self, mocker):
        """Verify the principal is still refused by every ``is_admin`` check.

        The bypass is scoped to this gate and keyed on identity, not on rank:
        the principal holds ``VIEWER``, so ``get_current_admin`` rejects it as
        before.
        """
        secret = "supersecret"
        mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(secret))
        principal = await get_current_user(secret)

        assert principal.role is UserRole.VIEWER
        assert principal.is_admin is False
        with pytest.raises(HTTPForbiddenException):
            await get_current_admin(principal)

    @pytest.mark.asyncio
    async def test_exempt_endpoint_admits_a_non_admin(self, casdoor_mock):
        """Verify a registered read-shaped route is admitted for a non-admin.

        Also pins that ``allow_non_admin_mutation`` sits below ``@router.post``
        on ``latest_task_history``: applied above it, the registered object
        would not be the one FastAPI stores as ``APIRoute.endpoint`` and this
        request would 403 instead.
        """
        request = make_request(
            "POST", authorization="Bearer valid_token", endpoint=latest_task_history
        )

        assert await require_admin_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_exempt_endpoint_is_decided_before_any_credential_handling(self):
        """Verify an exempt route keeps whatever auth its own ``dependencies`` declare.

        The gate must not impose a credential of its own on a route it exempts.
        """
        request = make_request("POST", endpoint=latest_task_history)

        assert await require_admin_for_unsafe_methods(request) is None
