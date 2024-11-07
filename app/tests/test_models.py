"""Define tests for the app.models module."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.core.auth.models import OAuthToken
from app.models import CasdoorTokenPayload, CasdoorUser


class TestCasdoorTokenPayload:
    """Test suite for CasdoorTokenPayload model validation and methods."""

    def test_model_validate(self, casdoor_token_payload_data, casdoor_mock):
        """Verify CasdoorTokenPayload model validates data correctly."""
        token_payload = CasdoorTokenPayload.model_validate(casdoor_token_payload_data)
        assert token_payload.iss == casdoor_token_payload_data["iss"]
        assert token_payload.sub == casdoor_token_payload_data["sub"]
        assert token_payload.aud == casdoor_token_payload_data["aud"]
        assert token_payload.exp == datetime.fromisoformat(
            casdoor_token_payload_data["exp"]
        )
        assert token_payload.nbf == datetime.fromisoformat(
            casdoor_token_payload_data["nbf"]
        )
        assert token_payload.jti == casdoor_token_payload_data["jti"]
        assert token_payload.username == casdoor_token_payload_data["username"]
        assert token_payload.active == casdoor_token_payload_data["active"]

    @pytest.mark.parametrize(
        "invalid_username",
        [
            "_username",
            "username_",
            "-username",
            "username-",
            "invalid--username",
            "invalid__username",
            "usern@me",
        ],
    )
    def test_validate_casdoor_username(
        self, invalid_username, casdoor_token_payload_data, casdoor_mock
    ):
        """Verify invalid usernames raise a ValidationError."""
        casdoor_token_payload_data["username"] = invalid_username
        with pytest.raises(ValidationError, match="String should match pattern"):
            CasdoorTokenPayload.model_validate(casdoor_token_payload_data)

    def test_validate_iss(
        self, casdoor_allowed_issuer, casdoor_disallowed_issuer, casdoor_mock, mocker
    ):
        """Verify issuer validation logic."""
        assert (
            CasdoorTokenPayload.validate_iss(casdoor_allowed_issuer)
            == casdoor_allowed_issuer
        )
        with pytest.raises(ValueError, match="Unknown token issuer"):
            CasdoorTokenPayload.validate_iss(casdoor_disallowed_issuer)
        mocker.patch("app.core.config.settings.CASDOOR.allowed_issuers", new="*")
        assert (
            CasdoorTokenPayload.validate_iss(casdoor_disallowed_issuer)
            == casdoor_disallowed_issuer
        )

    def test_validate_aud(self, casdoor_client_id, casdoor_mock):
        """Verify audience validation logic."""
        assert CasdoorTokenPayload.validate_aud([casdoor_client_id]) == [
            casdoor_client_id
        ]
        with pytest.raises(ValueError, match="Client ID not part of audience"):
            CasdoorTokenPayload.validate_aud([])

    @pytest.mark.asyncio
    async def test_from_jwt(self, casdoor_token_payload_data, casdoor_mock):
        """Verify CasdoorTokenPayload creation from JWT."""
        token = "access_token"
        token_payload = await CasdoorTokenPayload.from_jwt(token)
        assert token_payload.iss == casdoor_token_payload_data["iss"]
        assert token_payload.sub == casdoor_token_payload_data["sub"]
        assert token_payload.aud == casdoor_token_payload_data["aud"]
        assert token_payload.exp == datetime.fromisoformat(
            casdoor_token_payload_data["exp"]
        )
        assert token_payload.nbf == datetime.fromisoformat(
            casdoor_token_payload_data["nbf"]
        )
        assert token_payload.jti == casdoor_token_payload_data["jti"]
        assert token_payload.username == casdoor_token_payload_data["username"]
        assert token_payload.active == casdoor_token_payload_data["active"]
        casdoor_mock.introspect_token.assert_awaited_once_with(token)


class TestCasdoorUser:
    """Test suite for CasdoorUser model validation and OAuth operations."""

    def test_model_validate(self, casdoor_user_data, casdoor_mock):
        """Verify CasdoorUser model validates data correctly."""
        user = CasdoorUser.model_validate(casdoor_user_data)
        assert str(user.id) == casdoor_user_data["id"]
        assert user.username == casdoor_user_data["username"]
        assert user.email == casdoor_user_data["email"]
        assert user.first_name == casdoor_user_data["first_name"]
        assert user.last_name == casdoor_user_data["last_name"]
        assert (
            user.full_name
            == f"{casdoor_user_data['first_name']} {casdoor_user_data['last_name']}"
        )
        assert user.is_admin == casdoor_user_data["is_admin"]
        assert user.created_time == datetime.fromisoformat(
            casdoor_user_data["created_time"]
        )
        assert user.updated_time is None
        assert user.owner == casdoor_user_data["owner"]
        assert user.is_forbidden == casdoor_user_data["is_forbidden"]
        assert user.is_deleted == casdoor_user_data["is_deleted"]

    def test_is_active(self, casdoor_user_data, casdoor_mock):
        """Verify is_active property reflects user status."""
        user = CasdoorUser.model_validate(casdoor_user_data)
        assert user.is_active
        user.is_forbidden = True
        assert not user.is_active
        user.is_forbidden = False
        user.is_deleted = True
        assert not user.is_active

    @pytest.mark.asyncio
    async def test_get_oauth_token_with_code(self, oauth_token, casdoor_mock):
        """Verify OAuth token retrieval using authorization code."""
        code = "test_code"
        new_token = await CasdoorUser.get_oauth_token(code=code)
        assert isinstance(new_token, OAuthToken)
        assert new_token.model_dump() == oauth_token.model_dump()
        casdoor_mock.get_access_token.assert_awaited_once_with(code, None, None)

    @pytest.mark.asyncio
    async def test_get_oauth_token_with_username_password(
        self, oauth_token, casdoor_mock
    ):
        """Verify OAuth token retrieval with username and password."""
        username = "test_username"
        password = "test_password"

        new_token = await CasdoorUser.get_oauth_token(
            username=username, password=password
        )
        assert isinstance(new_token, OAuthToken)
        assert new_token.model_dump() == oauth_token.model_dump()
        casdoor_mock.get_access_token.assert_awaited_once_with(None, username, password)

    @pytest.mark.asyncio
    async def test_get_oauth_token_with_refresh_token(self, oauth_token, casdoor_mock):
        """Verify OAuth token retrieval using refresh token."""
        refresh_token = "test_refresh_token"

        new_token = await CasdoorUser.get_oauth_token(refresh_token=refresh_token)
        assert isinstance(new_token, OAuthToken)
        assert new_token.model_dump() == oauth_token.model_dump()
        casdoor_mock.refresh_token_request.assert_awaited_once_with(refresh_token)

    @pytest.mark.asyncio
    async def test_invalidate_oauth_token(
        self, casdoor_token_payload_data, refresh_token, casdoor_mock
    ):
        """Verify invalidating an OAuth token."""
        access_token = "test_access_token"
        await CasdoorUser.invalidate_oauth_token(access_token)
        casdoor_mock.introspect_token.assert_awaited_once_with(access_token)
        casdoor_mock.get_token.assert_awaited_once_with(
            casdoor_token_payload_data["jti"]
        )
        casdoor_mock.refresh_token_request.assert_awaited_once_with(refresh_token)

    @pytest.mark.asyncio
    async def test_get_user(self, valid_username, casdoor_mock):
        """Verify retrieving a user by username."""
        user = await CasdoorUser.get_user(valid_username)
        assert isinstance(user, CasdoorUser)
        assert user.username == valid_username
        casdoor_mock.get_user.assert_awaited_once_with(valid_username)

    @pytest.mark.asyncio
    async def test_get_users(self, valid_username, casdoor_mock):
        """Verify retrieving all users."""
        users = await CasdoorUser.get_users()
        assert len(users) == 1
        user = users[0]
        assert isinstance(user, CasdoorUser)
        assert user.username == valid_username
        casdoor_mock.get_users.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_from_token_payload(
        self, valid_username, casdoor_token_payload_data, casdoor_mock
    ):
        """Verify creating CasdoorUser from token payload."""
        token_payload = CasdoorTokenPayload.model_validate(casdoor_token_payload_data)
        user = await CasdoorUser.from_token_payload(token_payload)
        assert isinstance(user, CasdoorUser)
        assert user.username == token_payload.username
        casdoor_mock.get_user.assert_awaited_once_with(token_payload.username)

    @pytest.mark.asyncio
    async def test_from_jwt(self, valid_username, casdoor_mock):
        """Verify creating CasdoorUser from JWT."""
        token = "test_access_token"
        user = await CasdoorUser.from_jwt(token)
        assert isinstance(user, CasdoorUser)
        assert user.username == valid_username
        assert user.access_token == token
        casdoor_mock.introspect_token.assert_awaited_once_with(token)
        casdoor_mock.get_user.assert_awaited_once_with(valid_username)

    @pytest.mark.asyncio
    async def test_from_code(self, valid_username, oauth_token, casdoor_mock):
        """Verify creating CasdoorUser from authorization code."""
        code = "test_code"
        user = await CasdoorUser.from_code(code)
        assert isinstance(user, CasdoorUser)
        assert user.username == valid_username
        casdoor_mock.get_access_token.assert_awaited_once_with(code, None, None)
        casdoor_mock.introspect_token.assert_awaited_once_with(oauth_token.access_token)
        casdoor_mock.get_user.assert_awaited_once_with(valid_username)

    @pytest.mark.asyncio
    async def test_from_password(self, valid_username, oauth_token, casdoor_mock):
        """Verify creating CasdoorUser from username and password."""
        password = "test_password"
        user = await CasdoorUser.from_password(valid_username, password)
        assert isinstance(user, CasdoorUser)
        assert user.username == valid_username
        casdoor_mock.get_access_token.assert_awaited_once_with(
            None, valid_username, password
        )
        casdoor_mock.introspect_token.assert_awaited_once_with(oauth_token.access_token)
        casdoor_mock.get_user.assert_awaited_once_with(valid_username)
