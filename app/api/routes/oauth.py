# Copyright 2025 Percona LLC
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

"""Define the API routes for OAuth authentication."""

import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError

from app.core.auth.exceptions import HTTPUnauthorizedException, InactiveUserException
from app.core.auth.models import OAuthToken
from app.core.auth.utils import get_user_model

logger = logging.getLogger(__name__)

router = APIRouter()

User = get_user_model()


# TODO(yan): Prevent malicious account lockout
# SEP-277
@router.post("/token")
async def create_oauth_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> OAuthToken:
    """Generate an OAuth token for a user from their username and password.

    :param form_data: The form data containing username and password.
    :type form_data: OAuth2PasswordRequestForm
    :return: The OAuth token for the user.
    :rtype: OAuthToken
    :raises InactiveUserException: If the user is not active.
    """
    oauth_token = await User.get_oauth_token(
        username=form_data.username,
        password=form_data.password,
    )
    user = await User.from_jwt(oauth_token.access_token)
    if not user.is_active:
        raise InactiveUserException

    return oauth_token


@router.post("/refresh")
async def refresh_token(token: Annotated[str, Body()]) -> OAuthToken:
    """Generate an OAuth token for a user from a refresh token.

    :param token: The refresh token to use for generating a new access token.
    :type token: str
    :return: The new OAuth token for the user.
    :rtype: OAuthToken
    :raises HTTPUnauthorizedException: If the refresh token is invalid, expired, or
        revoked.
    :raises InactiveUserException: If the user is not active.
    """
    try:
        oauth_token = await User.get_oauth_token(refresh_token=token)
    except ValidationError:
        logger.exception("Failed to refresh token")
        raise HTTPUnauthorizedException(
            "Refresh token is invalid, expired, or revoked",
        ) from None

    user = await User.from_jwt(oauth_token.access_token)
    if not user.is_active:
        raise InactiveUserException

    return oauth_token
