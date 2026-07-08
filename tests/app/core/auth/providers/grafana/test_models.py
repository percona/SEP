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

"""Define tests for the Grafana user and token-payload models."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from itsdangerous import URLSafeTimedSerializer
from pydantic import ValidationError

from app.core.auth.models import OAuthToken
from app.core.auth.providers.grafana.models import GrafanaTokenPayload, GrafanaUser
from app.core.auth.providers.grafana.sdk import GrafanaException
from app.core.config import settings
from tests.app.factories import GrafanaUserFactory


class TestGrafanaUserIdentity:
    """Test the identity mapping and signed-assertion round-trip."""

    @pytest.mark.asyncio
    async def test_get_oauth_token_round_trips_to_user(
        self, grafana_mock, grafana_user_record
    ):
        """Verify a minted assertion reverses back into the same user."""
        oauth = await GrafanaUser.get_oauth_token(username="alice", password="secret")
        assert isinstance(oauth, OAuthToken)
        assert oauth.token_type == "Bearer"
        assert oauth.access_token
        assert oauth.refresh_token

        user = await GrafanaUser.from_jwt(oauth.access_token)

        assert user.username == grafana_user_record["login"]
        assert user.email == grafana_user_record["email"]
        assert user.is_admin is False
        assert user.access_token == oauth.access_token
        grafana_mock.login.assert_awaited_once_with("alice", "secret")
        grafana_mock.get_current_user.assert_awaited_once()
        grafana_mock.get_current_user_orgs.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_admin_survives_the_assertion_round_trip(
        self, grafana_mock, grafana_user_record
    ):
        """Verify ``is_admin`` is carried through mint and verified on decode."""
        grafana_mock.get_current_user.return_value = {
            **grafana_user_record,
            "isGrafanaAdmin": True,
        }
        oauth = await GrafanaUser.get_oauth_token(username="root", password="secret")

        user = await GrafanaUser.from_jwt(oauth.access_token)

        assert user.is_admin is True

    def test_id_is_stable_and_distinct_per_grafana_id(self, grafana_user_record):
        """Verify the SEP id is deterministic per Grafana numeric id."""
        first = GrafanaUser._from_grafana_record(grafana_user_record, [])
        again = GrafanaUser._from_grafana_record(grafana_user_record, [])
        other = GrafanaUser._from_grafana_record(
            {**grafana_user_record, "id": grafana_user_record["id"] + 1}, []
        )

        assert first.id == again.id
        assert other.id != first.id


class TestGrafanaAmbientSession:
    """Test the ambient-session grant (``oauth_token_from_session``)."""

    @pytest.mark.asyncio
    async def test_valid_session_mints_pair_without_login(
        self, grafana_mock, grafana_user_record
    ):
        """Verify a valid ambient session mints a pair, reusing the cookie (no login)."""
        oauth = await GrafanaUser.oauth_token_from_session("ambient-session")

        assert isinstance(oauth, OAuthToken)
        assert oauth.access_token
        assert oauth.refresh_token
        user = await GrafanaUser.from_jwt(oauth.access_token)
        assert user.username == grafana_user_record["login"]
        grafana_mock.get_current_user.assert_awaited_once_with("ambient-session")
        grafana_mock.get_current_user_orgs.assert_awaited_once_with("ambient-session")
        grafana_mock.login.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_admin_survives(self, grafana_mock, grafana_user_record):
        """Verify an admin ambient session decodes to an admin access assertion."""
        grafana_mock.get_current_user.return_value = {
            **grafana_user_record,
            "isGrafanaAdmin": True,
        }

        oauth = await GrafanaUser.oauth_token_from_session("ambient-session")

        user = await GrafanaUser.from_jwt(oauth.access_token)
        assert user.is_admin is True

    @pytest.mark.asyncio
    async def test_rejected_session_returns_none(self, grafana_mock):
        """Verify a Grafana 401 (rejected session) returns ``None`` for a silent fallback."""
        grafana_mock.get_current_user.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

        assert await GrafanaUser.oauth_token_from_session("stale") is None

    @pytest.mark.asyncio
    async def test_non_401_error_propagates(self, grafana_mock):
        """Verify a non-401 upstream error propagates instead of masking as no-session."""
        grafana_mock.get_current_user.side_effect = HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY
        )

        with pytest.raises(HTTPException):
            await GrafanaUser.oauth_token_from_session("s")


class TestGrafanaUserSerialization:
    """Test the JSON serialization contract the React SPA depends on."""

    def test_serializes_with_camelcase_aliases(self):
        """Verify ``by_alias`` dumps camelCase keys the SPA reads (e.g. ``isAdmin``)."""
        user = GrafanaUserFactory.build(is_admin=True)

        dumped = user.model_dump(by_alias=True)

        for alias in ("isAdmin", "firstName", "lastName", "createdTime", "updatedTime"):
            assert alias in dumped
        assert dumped["isAdmin"] is True


class TestGrafanaUserFromJwt:
    """Test signature verification in ``from_jwt``."""

    @pytest.mark.asyncio
    async def test_rejects_tampered_token(self, grafana_mock):
        """Verify a non-decodable token raises ``ValidationError``."""
        with pytest.raises(ValidationError):
            await GrafanaUser.from_jwt("not-a-valid-signed-token")

    @pytest.mark.asyncio
    async def test_rejects_wrong_salt_token(self, grafana_mock):
        """Verify a token signed with a different salt raises ``ValidationError``."""
        forged = URLSafeTimedSerializer(
            settings.SECRET_KEY.get_secret_value(), salt="wrong-salt"
        ).dumps({"id": str(uuid4()), "username": "x", "email": "", "is_admin": True})

        with pytest.raises(ValidationError):
            await GrafanaUser.from_jwt(forged)

    @pytest.mark.asyncio
    async def test_rejects_expired_token(self, grafana_mock, mocker):
        """Verify an access assertion past its lifetime raises ``ValidationError``."""
        oauth = await GrafanaUser.get_oauth_token(username="alice", password="secret")
        mocker.patch.object(grafana_mock, "access_token_max_age", timedelta(seconds=-1))

        with pytest.raises(ValidationError):
            await GrafanaUser.from_jwt(oauth.access_token)

    @pytest.mark.asyncio
    async def test_rejects_refresh_token_as_bearer(self, grafana_mock):
        """Verify a refresh assertion cannot authenticate as a Bearer token."""
        oauth = await GrafanaUser.get_oauth_token(username="alice", password="secret")
        with pytest.raises(ValidationError):
            await GrafanaUser.from_jwt(oauth.refresh_token)


class TestGrafanaAdminDerivation:
    """Test how ``is_admin`` is derived from Grafana records and orgs."""

    def test_server_admin_flag(self, grafana_user_record):
        """Verify ``isGrafanaAdmin`` maps to admin regardless of orgs."""
        record = {**grafana_user_record, "isGrafanaAdmin": True}
        assert GrafanaUser._from_grafana_record(record, []).is_admin is True

    def test_org_admin_role(self, grafana_user_record):
        """Verify an ``Admin`` org role maps to admin."""
        record = {**grafana_user_record, "isGrafanaAdmin": False}
        user = GrafanaUser._from_grafana_record(record, [{"role": "Admin"}])
        assert user.is_admin is True

    def test_non_admin(self, grafana_user_record):
        """Verify neither server-admin nor org-admin yields a non-admin."""
        record = {**grafana_user_record, "isGrafanaAdmin": False}
        user = GrafanaUser._from_grafana_record(record, [{"role": "Viewer"}])
        assert user.is_admin is False

    def test_empty_orgs_is_non_admin(self, grafana_user_record):
        """Verify an empty orgs list is a non-admin, not an error."""
        record = {**grafana_user_record, "isGrafanaAdmin": False}
        assert GrafanaUser._from_grafana_record(record, []).is_admin is False


class TestGrafanaUserLookup:
    """Test the programmatic ``get_user`` / ``get_users`` mappings."""

    @pytest.mark.asyncio
    async def test_get_user(self, grafana_mock, grafana_user_record):
        """Verify get_user maps a looked-up record to a ``GrafanaUser``."""
        user = await GrafanaUser.get_user(grafana_user_record["login"])
        assert isinstance(user, GrafanaUser)
        assert user.username == grafana_user_record["login"]
        grafana_mock.lookup_user.assert_awaited_once_with(grafana_user_record["login"])

    @pytest.mark.asyncio
    async def test_get_users(self, grafana_mock, grafana_org_users):
        """Verify get_users maps org-user records to ``GrafanaUser`` instances."""
        users = await GrafanaUser.get_users()
        assert len(users) == len(grafana_org_users)
        assert all(isinstance(user, GrafanaUser) for user in users)
        assert users[0].username == grafana_org_users[0]["login"]
        grafana_mock.get_org_users.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_users_empty(self, grafana_mock):
        """Verify an empty org-users list returns an empty list, not an error."""
        grafana_mock.get_org_users.return_value = []
        assert await GrafanaUser.get_users() == []

    @pytest.mark.asyncio
    async def test_get_users_record_missing_login_fails_closed(self, grafana_mock):
        """Verify a malformed org-user record propagates a ``KeyError``."""
        grafana_mock.get_org_users.return_value = [{"userId": 1, "role": "Viewer"}]
        with pytest.raises(KeyError):
            await GrafanaUser.get_users()


class TestGrafanaUserEdgeCases:
    """Test edge cases in record mapping."""

    def test_missing_email_defaults_to_empty(self, grafana_user_record):
        """Verify an absent email maps to an empty string."""
        record = {k: v for k, v in grafana_user_record.items() if k != "email"}
        assert GrafanaUser._from_grafana_record(record, []).email == ""

    def test_record_missing_id_fails_closed(self, grafana_user_record):
        """Verify a record without a numeric id propagates a ``KeyError``."""
        record = {k: v for k, v in grafana_user_record.items() if k != "id"}
        with pytest.raises(KeyError):
            GrafanaUser._from_grafana_record(record, [])

    def test_accepts_non_email_login(self):
        """Verify a non-email address such as ``admin@localhost`` validates."""
        user = GrafanaUserFactory.build(email="admin@localhost")
        assert user.email == "admin@localhost"


class TestGrafanaUnsupportedGrants:
    """Test that unsupported auth flows fail loudly with ``GrafanaException``."""

    @pytest.mark.asyncio
    async def test_get_oauth_token_with_code(self):
        """Verify the authorization-code grant is unsupported."""
        with pytest.raises(GrafanaException):
            await GrafanaUser.get_oauth_token(code="some-code")

    @pytest.mark.asyncio
    async def test_from_code(self):
        """Verify from_code is unsupported."""
        with pytest.raises(GrafanaException):
            await GrafanaUser.from_code("some-code")

    @pytest.mark.asyncio
    async def test_from_token_payload(self):
        """Verify from_token_payload is unsupported."""
        with pytest.raises(GrafanaException):
            await GrafanaUser.from_token_payload(None)

    @pytest.mark.asyncio
    async def test_token_payload_from_jwt(self):
        """Verify ``GrafanaTokenPayload.from_jwt`` is unsupported."""
        with pytest.raises(GrafanaException):
            await GrafanaTokenPayload.from_jwt("anything")


class TestGrafanaRefreshGrant:
    """Test the SPA refresh grant (SEP-minted refresh assertions)."""

    @pytest.mark.asyncio
    async def test_refresh_remints_a_rotated_pair(
        self, grafana_mock, grafana_user_record
    ):
        """Verify the refresh grant re-mints a usable pair without calling Grafana."""
        login = await GrafanaUser.get_oauth_token(username="alice", password="secret")

        refreshed = await GrafanaUser.get_oauth_token(refresh_token=login.refresh_token)

        assert refreshed.access_token
        assert refreshed.refresh_token
        user = await GrafanaUser.from_jwt(refreshed.access_token)
        assert user.username == grafana_user_record["login"]
        grafana_mock.login.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_rejects_an_access_token(self, grafana_mock):
        """Verify an access assertion cannot be replayed at the refresh grant."""
        login = await GrafanaUser.get_oauth_token(username="alice", password="secret")
        with pytest.raises(ValidationError):
            await GrafanaUser.get_oauth_token(refresh_token=login.access_token)

    @pytest.mark.asyncio
    async def test_refresh_rejects_expired_refresh(self, grafana_mock, mocker):
        """Verify an expired refresh assertion raises ``ValidationError``."""
        login = await GrafanaUser.get_oauth_token(username="alice", password="secret")
        mocker.patch.object(
            grafana_mock, "refresh_token_max_age", timedelta(seconds=-1)
        )
        with pytest.raises(ValidationError):
            await GrafanaUser.get_oauth_token(refresh_token=login.refresh_token)


class TestGrafanaInvalidation:
    """Test that token invalidation is a safe no-op for Grafana."""

    @pytest.mark.asyncio
    async def test_invalidate_oauth_token_is_noop(self):
        """Verify invalidate_oauth_token returns None without raising."""
        assert await GrafanaUser.invalidate_oauth_token("token") is None

    @pytest.mark.asyncio
    async def test_invalidate_tokens_for_user_is_noop(self):
        """Verify invalidate_tokens_for_user returns None without raising."""
        assert await GrafanaUser.invalidate_tokens_for_user("alice") is None
