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

import pytest
from pydantic import SecretStr

from app.api.deps import get_current_admin, get_current_user, SERVICE_PRINCIPAL_ID
from app.core.auth.exceptions import HTTPForbiddenException, HTTPUnauthorizedException
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
