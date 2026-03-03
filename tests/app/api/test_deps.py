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

from app.api.deps import get_current_admin, get_current_user
from app.core.auth.exceptions import HTTPForbiddenException, HTTPUnauthorizedException
from app.core.auth.utils import get_user_model

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
