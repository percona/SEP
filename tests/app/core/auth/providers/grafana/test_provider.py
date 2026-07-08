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

"""Define tests for the Grafana authentication-provider bundle."""

from datetime import timedelta

import pytest

from app.core.auth.providers.grafana.models import GrafanaTokenPayload, GrafanaUser
from app.core.auth.providers.grafana.provider import GrafanaAuthProvider


def _provider() -> GrafanaAuthProvider:
    """Build a ``GrafanaAuthProvider`` with minimal config."""
    return GrafanaAuthProvider(
        endpoint="https://grafana.example.com",
        service_account_token="svc-token",
    )


class TestGrafanaAuthProviderBundle:
    """Test the Grafana provider bundle wiring and lifecycle."""

    def test_user_model_wired(self):
        """Verify the provider exposes the Grafana user model."""
        assert GrafanaAuthProvider.user_model is GrafanaUser

    def test_token_payload_model_wired(self):
        """Verify the provider exposes the Grafana token-payload model."""
        assert GrafanaAuthProvider.token_payload_model is GrafanaTokenPayload

    def test_supports_ambient_session(self):
        """Verify the Grafana provider advertises ambient-session support."""
        assert GrafanaAuthProvider.supports_ambient_session is True

    def test_provider_is_a_grafana_sdk(self):
        """Verify the provider carries the flat Grafana SDK config."""
        provider = _provider()
        assert provider.service_account_token.get_secret_value() == "svc-token"
        assert provider.access_token_max_age == timedelta(hours=1)
        assert provider.refresh_token_max_age == timedelta(days=7)
        assert callable(provider.get_org_users)

    @pytest.mark.asyncio
    async def test_lifespan_enters_and_exits_the_sdk(self, mocker):
        """Verify ``lifespan`` enters and exits the provider's SDK context."""
        provider = _provider()
        enter = mocker.patch.object(
            GrafanaAuthProvider,
            "__aenter__",
            mocker.AsyncMock(return_value=provider),
        )
        exit_ = mocker.patch.object(
            GrafanaAuthProvider,
            "__aexit__",
            mocker.AsyncMock(return_value=False),
        )
        async with provider.lifespan():
            pass
        enter.assert_awaited_once()
        exit_.assert_awaited_once()


class TestResolveAmbientSession:
    """Test the provider's ambient-session seam (``resolve_ambient_session``)."""

    @pytest.mark.asyncio
    async def test_returns_none_when_session_cookie_absent(self, mocker):
        """Verify a missing session cookie yields ``None`` without an upstream call."""
        provider = _provider()
        mint = mocker.patch.object(
            GrafanaUser, "oauth_token_from_session", mocker.AsyncMock()
        )
        assert await provider.resolve_ambient_session({"unrelated": "x"}) is None
        mint.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mints_token_from_session_cookie(self, mocker):
        """Verify the provider delegates its session cookie to the user model."""
        provider = _provider()
        token = mocker.Mock()
        mint = mocker.patch.object(
            GrafanaUser,
            "oauth_token_from_session",
            mocker.AsyncMock(return_value=token),
        )
        result = await provider.resolve_ambient_session(
            {provider.session_cookie_name: "ambient"}
        )
        assert result is token
        mint.assert_awaited_once_with("ambient")
