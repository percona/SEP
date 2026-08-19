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

from app.core.auth.models import (
    OAuthToken,
    SessionExchangeTokenResponse,
    UserRole,
)
from app.core.auth.providers.grafana.models import (
    _TOKEN_SERIALIZER,
    _TokenType,
    GrafanaTokenPayload,
    GrafanaUser,
)
from app.core.auth.providers.grafana.sdk import GrafanaException
from app.core.config import settings
from tests.app.conftest import make_roleless_grafana_assertion
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
        user = GrafanaUserFactory.build(role=UserRole.ADMIN)

        dumped = user.model_dump(by_alias=True)

        for alias in ("isAdmin", "firstName", "lastName", "createdTime", "updatedTime"):
            assert alias in dumped
        assert dumped["isAdmin"] is True


class TestGrafanaAssertionRoleRoundTrip:
    """Verify the role a minted assertion decodes to when it comes back.

    The assertion carries the role as its own claim, so every role survives the
    round trip rather than collapsing onto the admin boundary. An assertion
    carrying no such claim predates the claim and is refused.
    """

    @pytest.mark.parametrize(
        ("role", "expected_admin"),
        [
            (UserRole.SUPER_ADMIN, True),
            (UserRole.ADMIN, True),
            (UserRole.EDITOR, False),
            (UserRole.VIEWER, False),
            (UserRole.NONE, False),
        ],
    )
    @pytest.mark.parametrize(
        "token_type", [_TokenType.ACCESS, _TokenType.REFRESH, _TokenType.EXCHANGE]
    )
    def test_every_role_round_trips_to_itself(
        self, grafana_mock, token_type, role, expected_admin
    ):
        """Verify every assertion type carries its role back unchanged."""
        minted = GrafanaUser._mint(GrafanaUserFactory.build(role=role), token_type)

        decoded = GrafanaUser.model_validate(minted, context={"token_type": token_type})

        assert decoded.role is role
        assert decoded.is_admin is expected_admin

    @pytest.mark.parametrize(
        "token_type", [_TokenType.ACCESS, _TokenType.REFRESH, _TokenType.EXCHANGE]
    )
    def test_an_assertion_minted_before_the_claim_is_refused(
        self, grafana_mock, token_type
    ):
        """Verify a payload carrying only the legacy claim set is refused.

        This is the shape every assertion in flight during the rollout has: no
        ``role`` key at all. Refusing it rather than rebuilding a role from
        ``is_admin`` is what keeps a degraded role out of every assertion
        re-minted from it.
        """
        legacy = _TOKEN_SERIALIZER.dumps(
            {
                "id": str(uuid4()),
                "username": "alice",
                "email": "",
                "is_admin": True,
                "typ": token_type,
            }
        )

        with pytest.raises(ValidationError):
            GrafanaUser.model_validate(legacy, context={"token_type": token_type})

    def test_the_shared_roleless_helper_signs_a_verifiable_assertion(self):
        """Verify the helper the API-boundary tests use is signed the real way.

        Those tests assert only that a legacy assertion yields a 401, which a
        signature mismatch would also produce. Loading the helper's output with
        the module's own serializer pins it to the real key and salt, so a drift
        fails here instead of quietly hollowing out those tests.
        """
        payload = _TOKEN_SERIALIZER.loads(make_roleless_grafana_assertion("access"))

        assert "role" not in payload
        assert payload["typ"] == _TokenType.ACCESS

    def test_a_claim_naming_no_known_role_is_refused(self, grafana_mock):
        """Verify a claim outside the enum fails closed rather than defaulting."""
        payload = _TOKEN_SERIALIZER.dumps(
            {
                "id": str(uuid4()),
                "username": "alice",
                "email": "",
                "role": "wizard",
                "typ": _TokenType.ACCESS,
            }
        )

        with pytest.raises(ValidationError):
            GrafanaUser.model_validate(payload)

    def test_a_claim_spelled_as_the_member_name_is_accepted(self, grafana_mock):
        """Verify the field coercion reads a member name as well as its value.

        Only SEP's own signing key can produce a payload at all, so the wider
        acceptance is documented here rather than narrowed.
        """
        payload = _TOKEN_SERIALIZER.dumps(
            {
                "id": str(uuid4()),
                "username": "alice",
                "email": "",
                "role": "SUPER_ADMIN",
                "typ": _TokenType.ACCESS,
            }
        )

        assert GrafanaUser.model_validate(payload).role is UserRole.SUPER_ADMIN


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


class TestGrafanaRoleDerivation:
    """Verify how the ordered role is derived from Grafana records and orgs.

    Every case pins ``is_admin`` alongside the role, so the boundary the admin
    gates read is asserted rather than implied.
    """

    @pytest.mark.parametrize(
        ("is_server_admin", "orgs", "expected_role", "expected_admin"),
        [
            (True, [], UserRole.SUPER_ADMIN, True),
            (True, [{"role": "Viewer"}], UserRole.SUPER_ADMIN, True),
            (False, [{"role": "Admin"}], UserRole.ADMIN, True),
            (False, [{"role": "Editor"}], UserRole.EDITOR, False),
            (False, [{"role": "Viewer"}], UserRole.VIEWER, False),
            (
                False,
                [{"role": "Viewer"}, {"role": "Editor"}, {"role": "Admin"}],
                UserRole.ADMIN,
                True,
            ),
            (
                False,
                [{"role": "Viewer"}, {"role": "Editor"}],
                UserRole.EDITOR,
                False,
            ),
            (False, [], UserRole.NONE, False),
            (False, [{"role": "Bogus"}], UserRole.NONE, False),
            (False, [{}], UserRole.NONE, False),
            (False, [{"role": "None"}], UserRole.NONE, False),
            (False, [{"role": "Bogus"}, {"role": "Editor"}], UserRole.EDITOR, False),
        ],
    )
    def test_user_record_maps_to_a_role(
        self,
        grafana_user_record,
        is_server_admin,
        orgs,
        expected_role,
        expected_admin,
    ):
        """Verify the server-admin flag outranks orgs, which flatten by rank."""
        record = {**grafana_user_record, "isGrafanaAdmin": is_server_admin}

        user = GrafanaUser._from_grafana_record(record, orgs)

        assert user.role is expected_role
        assert user.is_admin is expected_admin

    def test_absent_server_admin_flag_falls_through_to_orgs(self, grafana_user_record):
        """Verify an omitted ``isGrafanaAdmin`` is read as not a server admin."""
        record = {k: v for k, v in grafana_user_record.items() if k != "isGrafanaAdmin"}

        user = GrafanaUser._from_grafana_record(record, [{"role": "Editor"}])

        assert user.role is UserRole.EDITOR

    @pytest.mark.parametrize(
        ("org_role", "expected_role", "expected_admin"),
        [
            ("Admin", UserRole.ADMIN, True),
            ("Editor", UserRole.EDITOR, False),
            ("Viewer", UserRole.VIEWER, False),
            ("None", UserRole.NONE, False),
            ("Bogus", UserRole.NONE, False),
        ],
    )
    def test_org_user_record_maps_to_a_role(
        self, grafana_org_users, org_role, expected_role, expected_admin
    ):
        """Verify an org-users row maps its single role onto the ordered role."""
        record = {**grafana_org_users[0], "role": org_role}

        user = GrafanaUser._from_org_user_record(record)

        assert user.role is expected_role
        assert user.is_admin is expected_admin

    def test_org_user_record_without_a_role_is_lowest(self, grafana_org_users):
        """Verify a row carrying no role fails closed rather than defaulting up."""
        record = {k: v for k, v in grafana_org_users[0].items() if k != "role"}

        assert GrafanaUser._from_org_user_record(record).role is UserRole.NONE

    @pytest.mark.parametrize(
        ("is_server_admin", "expected_role"),
        [(True, UserRole.SUPER_ADMIN), (False, UserRole.NONE)],
    )
    @pytest.mark.asyncio
    async def test_get_user_decides_on_the_server_admin_flag_alone(
        self, grafana_mock, grafana_user_record, is_server_admin, expected_role
    ):
        """Verify the lookup path carries no orgs, so the flag alone ranks."""
        grafana_mock.lookup_user.return_value = {
            **grafana_user_record,
            "isGrafanaAdmin": is_server_admin,
        }

        user = await GrafanaUser.get_user(grafana_user_record["login"])

        assert user.role is expected_role


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
        self, grafana_mock, grafana_user_record, grafana_user_orgs
    ):
        """Verify the refresh grant re-mints a usable pair without calling Grafana.

        The re-mint reads the role off the presented assertion rather than
        Grafana, so an Editor must stay an Editor across the rotation.
        """
        grafana_mock.get_current_user_orgs.return_value = [
            {**grafana_user_orgs[0], "role": "Editor"}
        ]
        login = await GrafanaUser.get_oauth_token(username="alice", password="secret")

        refreshed = await GrafanaUser.get_oauth_token(refresh_token=login.refresh_token)

        assert refreshed.access_token
        assert refreshed.refresh_token
        user = await GrafanaUser.from_jwt(refreshed.access_token)
        assert user.username == grafana_user_record["login"]
        assert user.role is UserRole.EDITOR
        grafana_mock.login.assert_awaited_once()
        grafana_mock.get_current_user.assert_awaited_once()
        grafana_mock.get_current_user_orgs.assert_awaited_once()

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


class TestGrafanaSessionExchange:
    """Verify the session-exchange grant (``exchange_token_from_session``)."""

    @pytest.mark.asyncio
    async def test_valid_session_mints_an_exchange_assertion(
        self, grafana_mock, grafana_user_record
    ):
        """Verify a valid ambient session mints an exchange assertion and its TTL."""
        exchange = await GrafanaUser.exchange_token_from_session("ambient-session")

        assert isinstance(exchange, SessionExchangeTokenResponse)
        assert exchange.access_token
        assert exchange.expires_in == grafana_mock.exchange_token_max_age
        user = await GrafanaUser.from_bearer(exchange.access_token)
        assert user.username == grafana_user_record["login"]
        grafana_mock.get_current_user.assert_awaited_once_with("ambient-session")
        grafana_mock.login.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_claim_set_is_pinned(self, grafana_mock):
        """Verify the exchange assertion carries no claim beyond the identity set.

        Guards against a later change smuggling Grafana session material or a
        service-account credential into the minted payload.
        """
        exchange = await GrafanaUser.exchange_token_from_session("ambient-session")

        payload = _TOKEN_SERIALIZER.loads(exchange.access_token)

        assert set(payload) == {"id", "username", "email", "role", "is_admin", "typ"}
        assert payload["typ"] == "exchange"
        assert payload["role"] == "viewer"

    @pytest.mark.asyncio
    async def test_rejected_session_returns_none(self, grafana_mock):
        """Verify a Grafana 401 (rejected session) returns ``None``."""
        grafana_mock.get_current_user.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

        assert await GrafanaUser.exchange_token_from_session("stale") is None

    @pytest.mark.asyncio
    async def test_non_401_error_propagates(self, grafana_mock):
        """Verify a non-401 upstream error propagates instead of masking as no-session."""
        grafana_mock.get_current_user.side_effect = GrafanaException()

        with pytest.raises(HTTPException):
            await GrafanaUser.exchange_token_from_session("s")

    @pytest.mark.asyncio
    async def test_admin_survives(self, grafana_mock, grafana_user_record):
        """Verify an admin ambient session decodes to an admin exchange assertion."""
        grafana_mock.get_current_user.return_value = {
            **grafana_user_record,
            "isGrafanaAdmin": True,
        }

        exchange = await GrafanaUser.exchange_token_from_session("ambient-session")

        user = await GrafanaUser.from_bearer(exchange.access_token)
        assert user.is_admin is True


class TestGrafanaUserFromBearer:
    """Verify the Bearer-surface accepted-type set (``from_bearer``)."""

    @staticmethod
    async def _exchange_token(session: str = "ambient-session") -> str:
        """Mint an exchange assertion and return its token string."""
        exchange = await GrafanaUser.exchange_token_from_session(session)
        return exchange.access_token

    @pytest.mark.asyncio
    async def test_accepts_an_access_assertion(self, grafana_mock, grafana_user_record):
        """Verify the common Bearer credential still authenticates."""
        oauth = await GrafanaUser.get_oauth_token(username="alice", password="secret")

        user = await GrafanaUser.from_bearer(oauth.access_token)

        assert user.username == grafana_user_record["login"]
        assert user.access_token == oauth.access_token

    @pytest.mark.asyncio
    async def test_accepts_an_exchange_assertion(
        self, grafana_mock, grafana_user_record
    ):
        """Verify an exchange assertion authenticates on the Bearer surface."""
        token = await self._exchange_token()

        user = await GrafanaUser.from_bearer(token)

        assert user.username == grafana_user_record["login"]
        assert user.access_token == token

    @pytest.mark.asyncio
    async def test_rejects_a_refresh_assertion(self, grafana_mock):
        """Verify a refresh assertion is refused on the Bearer surface."""
        oauth = await GrafanaUser.get_oauth_token(username="alice", password="secret")

        with pytest.raises(ValidationError):
            await GrafanaUser.from_bearer(oauth.refresh_token)

    @pytest.mark.asyncio
    async def test_rejects_garbage(self, grafana_mock):
        """Verify a non-decodable credential is refused."""
        with pytest.raises(ValidationError):
            await GrafanaUser.from_bearer("not-a-valid-signed-token")

    @pytest.mark.asyncio
    async def test_rejects_an_empty_credential(self, grafana_mock):
        """Verify an empty credential is refused rather than decoded."""
        with pytest.raises(ValidationError):
            await GrafanaUser.from_bearer("")

    @pytest.mark.asyncio
    async def test_exchange_expiry_is_enforced_against_its_own_lifetime(
        self, grafana_mock, mocker
    ):
        """Verify an exchange assertion past *its* lifetime is refused.

        The access lifetime stays at its default, so an implementation that
        widened the accepted set without trying each type against its own
        ``max_age`` would silently accept this token for the full access hour.
        """
        token = await self._exchange_token()
        mocker.patch.object(
            grafana_mock, "exchange_token_max_age", timedelta(seconds=-1)
        )

        with pytest.raises(ValidationError):
            await GrafanaUser.from_bearer(token)

    @pytest.mark.asyncio
    async def test_rejects_an_expired_access_assertion(self, grafana_mock, mocker):
        """Verify an expired access assertion is not rescued by the exchange attempt."""
        oauth = await GrafanaUser.get_oauth_token(username="alice", password="secret")
        mocker.patch.object(grafana_mock, "access_token_max_age", timedelta(seconds=-1))

        with pytest.raises(ValidationError):
            await GrafanaUser.from_bearer(oauth.access_token)


class TestGrafanaExchangeTokenTypeIsolation:
    """Verify an exchange assertion is refused everywhere but the Bearer surface."""

    @pytest.mark.asyncio
    async def test_from_jwt_rejects_an_exchange_assertion(self, grafana_mock):
        """Verify the cookie/session surface refuses an exchange assertion."""
        exchange = await GrafanaUser.exchange_token_from_session("ambient-session")

        with pytest.raises(ValidationError):
            await GrafanaUser.from_jwt(exchange.access_token)

    @pytest.mark.asyncio
    async def test_refresh_grant_rejects_an_exchange_assertion(self, grafana_mock):
        """Verify an exchange assertion cannot be replayed at the refresh grant."""
        exchange = await GrafanaUser.exchange_token_from_session("ambient-session")

        with pytest.raises(ValidationError):
            await GrafanaUser.get_oauth_token(refresh_token=exchange.access_token)
