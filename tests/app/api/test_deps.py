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
from types import SimpleNamespace
from typing import Final

import pytest
from pydantic import SecretStr

from app.api.deps import (
    get_current_admin,
    get_current_user,
    require_minimum_role_for_unsafe_methods,
    SERVICE_PRINCIPAL_ID,
)
from app.core.auth.exceptions import HTTPForbiddenException, HTTPUnauthorizedException
from app.core.auth.models import UserRole
from app.core.auth.providers.grafana.models import GrafanaUser
from app.core.auth.utils import get_user_model
from app.core.config import settings
from app.sep.apps.alerts.api_routes import (
    alerts_api_pagerduty_delete,
    alerts_api_pagerduty_save,
    alerts_api_restore,
)
from app.tasks.routes import execute_task_name, latest_task_history
from tests.app.conftest import make_request, make_roleless_grafana_assertion

SERVICE_TOKEN: Final = "supersecret"

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

    ``app.api.deps.User`` is bound at import time, so ``grafana_mock`` — which
    patches the active-provider lookup — does not rebind it; each test patches
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

    @pytest.mark.asyncio
    async def test_an_editor_clears_a_route_classified_at_editor(
        self, grafana_mock, grafana_user_orgs
    ):
        """Verify a PMM Editor reaches a route SEP opened to that rank.

        The realistic PMM path end to end: the role survives the mint and the
        unmint, so the rank the gate compares is the one Grafana reported rather
        than one inferred from an admin flag.
        """
        grafana_mock.get_current_user_orgs.return_value = [
            {**grafana_user_orgs[0], "role": "Editor"}
        ]
        exchange = await GrafanaUser.exchange_token_from_session("ambient")
        request = make_request(
            "POST",
            authorization=f"Bearer {exchange.access_token}",
            endpoint=alerts_api_restore,
        )

        assert await require_minimum_role_for_unsafe_methods(request) is None


class TestRequireMinimumRoleForUnsafeMethods:
    """Cover the router-level minimum-role gate on mutating HTTP methods."""

    @pytest.fixture
    def as_role(self, casdoor_mock, casdoor_user_data, mocker):
        """Return a callable resolving the Bearer credential to a given rank.

        A Casdoor payload carrying a ``role`` of its own bypasses the
        admin-flag derivation, so the gate resolves a genuine identity at
        exactly the requested rank rather than one inferred from ``is_admin``.
        """

        def resolve_as(role: UserRole) -> None:
            mocker.patch(
                "app.core.auth.providers.casdoor.sdk.CasdoorSDK.get_user",
                new=mocker.AsyncMock(
                    return_value={**casdoor_user_data, "role": role.value}
                ),
            )

        return resolve_as

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    @pytest.mark.asyncio
    async def test_safe_methods_pass_without_any_credential(self, method):
        """Verify a safe method returns without touching authentication.

        ``GET /health`` is unauthenticated on all three services, so the gate
        must not resolve a user before deciding a read is allowed.
        """
        request = make_request(method)

        assert await require_minimum_role_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_a_safe_method_on_a_lowered_route_resolves_nothing_either(self):
        """Verify the method check runs ahead of the registry lookup.

        A registration lowers the bar for unsafe methods only, so a read on the
        same route keeps whatever authentication the route itself declares.
        """
        request = make_request("GET", endpoint=alerts_api_restore)

        assert await require_minimum_role_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_an_unregistered_route_refuses_a_non_admin(self, casdoor_mock):
        """Verify a route nobody classified still requires an administrator.

        This is the fail-closed default: a route added without a thought about
        authorization is admin-only rather than open.
        """
        request = make_request(
            "POST", authorization="Bearer valid_token", endpoint=execute_task_name
        )

        with pytest.raises(HTTPForbiddenException):
            await require_minimum_role_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_an_unmatched_request_refuses_a_non_admin(self, casdoor_mock):
        """Verify a request no route matched takes the default rather than passing.

        Nothing declares a method on a path that matched no route, so the scope
        carries no ``route`` at all and the lookup has no endpoint to key on.
        """
        request = make_request("POST", authorization="Bearer valid_token")

        with pytest.raises(HTTPForbiddenException):
            await require_minimum_role_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_a_route_without_an_endpoint_refuses_a_non_admin(self, casdoor_mock):
        """Verify a matched route carrying no endpoint takes the default.

        The lookup reads the attribute defensively, so a match that is not an
        ``APIRoute`` refuses rather than raising ``AttributeError`` into a 500.
        """
        request = make_request("POST", authorization="Bearer valid_token")
        request.scope["route"] = SimpleNamespace()

        with pytest.raises(HTTPForbiddenException):
            await require_minimum_role_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_an_admin_passes_an_unregistered_route(self, as_role):
        """Verify an administrator's mutation is admitted on the default."""
        as_role(UserRole.ADMIN)
        request = make_request(
            "POST", authorization="Bearer valid_token", endpoint=execute_task_name
        )

        assert await require_minimum_role_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_an_editor_is_refused_an_unregistered_route(self, as_role):
        """Verify the rank below the default gains nothing from the new tier."""
        as_role(UserRole.EDITOR)
        request = make_request(
            "POST", authorization="Bearer valid_token", endpoint=execute_task_name
        )

        with pytest.raises(HTTPForbiddenException):
            await require_minimum_role_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_an_editor_is_admitted_a_route_registered_at_editor(self, as_role):
        """Verify the rank a route names reaches it."""
        as_role(UserRole.EDITOR)
        request = make_request(
            "POST", authorization="Bearer valid_token", endpoint=alerts_api_restore
        )

        assert await require_minimum_role_for_unsafe_methods(request) is None

    @pytest.mark.parametrize(
        "role", [UserRole.ADMIN, UserRole.SUPER_ADMIN], ids=["admin", "super_admin"]
    )
    @pytest.mark.asyncio
    async def test_a_rank_above_the_minimum_is_admitted(self, as_role, role):
        """Verify the comparison is ordered rather than an equality on the rank.

        A route lowered to ``EDITOR`` widens who reaches it; it must not stop
        admitting the ranks that already did.
        """
        as_role(role)
        request = make_request(
            "POST", authorization="Bearer valid_token", endpoint=alerts_api_restore
        )

        assert await require_minimum_role_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_a_viewer_is_refused_a_route_registered_at_editor(self, as_role):
        """Verify a rank below the route's own minimum is still refused."""
        as_role(UserRole.VIEWER)
        request = make_request(
            "POST", authorization="Bearer valid_token", endpoint=alerts_api_restore
        )

        with pytest.raises(HTTPForbiddenException):
            await require_minimum_role_for_unsafe_methods(request)

    @pytest.mark.parametrize(
        "endpoint",
        [alerts_api_pagerduty_save, alerts_api_pagerduty_delete],
        ids=["save", "delete"],
    )
    @pytest.mark.asyncio
    async def test_an_editor_is_refused_the_pagerduty_routes(self, as_role, endpoint):
        """Verify the PagerDuty pair stays administrator-only.

        They sit beside the two template routes an Editor reaches on the same
        router, and carry third-party routing and an integration key rather
        than alert-template content.
        """
        as_role(UserRole.EDITOR)
        request = make_request(
            "POST", authorization="Bearer valid_token", endpoint=endpoint
        )

        with pytest.raises(HTTPForbiddenException):
            await require_minimum_role_for_unsafe_methods(request)

    @pytest.mark.parametrize(
        "authorization",
        [None, "Bearer invalid_token", f"Bearer {SERVICE_TOKEN}"],
        ids=["absent", "invalid", "service_principal"],
    )
    @pytest.mark.asyncio
    async def test_a_waived_route_admits_every_credential_shape(
        self, casdoor_mock, mocker, authorization
    ):
        """Verify a ``UserRole.NONE`` minimum is answered ahead of every credential path.

        The branch sits above the Bearer check, so neither an absent credential,
        one the provider would reject, nor the service principal's own token
        changes the answer — the route's own ``dependencies`` stay the only
        thing authenticating it.
        """
        mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(SERVICE_TOKEN))
        request = make_request(
            "POST", authorization=authorization, endpoint=latest_task_history
        )

        assert await require_minimum_role_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_a_waived_route_never_consults_the_auth_provider(
        self, casdoor_mock, mocker
    ):
        """Verify the credential a waived route carries is never validated.

        Introspection is where a Bearer credential is checked, so "decided
        before any credential handling" is only meaningful observed there: a
        credential the provider would reject arrives and the provider is never
        asked about it.
        """
        introspect = mocker.patch(
            "app.core.auth.providers.casdoor.sdk.CasdoorSDK.introspect_token",
            new=mocker.AsyncMock(return_value={}),
        )
        request = make_request(
            "POST", authorization="Bearer invalid_token", endpoint=latest_task_history
        )

        assert await require_minimum_role_for_unsafe_methods(request) is None
        introspect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_lowered_route_still_demands_a_credential(self):
        """Verify lowering a route's rank does not waive authentication on it.

        Only ``UserRole.NONE`` reaches the branch that skips the Bearer check,
        so a credential-less caller gets a 401 on an ``EDITOR`` route, not the
        403 the rank comparison would give.
        """
        request = make_request("POST", endpoint=alerts_api_restore)

        with pytest.raises(HTTPUnauthorizedException):
            await require_minimum_role_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_missing_authorization_header_is_unauthorized(self):
        """Verify a credential-less mutation raises the project 401.

        The header is checked before ``oauth2_scheme``, which carries
        ``auto_error=True`` and would raise a bare Starlette ``HTTPException``.
        """
        with pytest.raises(HTTPUnauthorizedException):
            await require_minimum_role_for_unsafe_methods(make_request("POST"))

    @pytest.mark.asyncio
    async def test_non_bearer_authorization_header_is_unauthorized(self):
        """Verify a non-Bearer credential is refused before token validation."""
        request = make_request("POST", authorization="Basic dXNlcjpwYXNz")

        with pytest.raises(HTTPUnauthorizedException):
            await require_minimum_role_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_invalid_token_is_never_admitted(self, casdoor_mock, mocker):
        """Verify a Bearer credential that fails validation is refused."""
        mocker.patch(
            "app.core.auth.providers.casdoor.sdk.CasdoorSDK.introspect_token",
            new=mocker.AsyncMock(return_value={}),
        )
        request = make_request("POST", authorization="Bearer invalid_token")

        with pytest.raises(HTTPUnauthorizedException):
            await require_minimum_role_for_unsafe_methods(request)

    @pytest.mark.asyncio
    async def test_service_principal_is_admitted_by_identity(self, mocker):
        """Verify ``SEP_INTERNAL_TOKEN``'s principal passes the gate.

        Scheduled inventory sync and scheduled execution authenticate with this
        token and write through the gated services. The principal holds
        ``VIEWER``, so only the identity check keeps them working.
        """
        mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(SERVICE_TOKEN))
        request = make_request("POST", authorization=f"Bearer {SERVICE_TOKEN}")

        assert await require_minimum_role_for_unsafe_methods(request) is None

    @pytest.mark.asyncio
    async def test_service_principal_gains_nothing_beyond_this_gate(self, mocker):
        """Verify the principal is still refused by every ``is_admin`` check.

        The bypass is scoped to this gate and keyed on identity, not on rank:
        the principal holds ``VIEWER``, so ``get_current_admin`` rejects it as
        before.
        """
        mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(SERVICE_TOKEN))
        principal = await get_current_user(SERVICE_TOKEN)

        assert principal.role is UserRole.VIEWER
        assert principal.is_admin is False
        with pytest.raises(HTTPForbiddenException):
            await get_current_admin(principal)
