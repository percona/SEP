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

"""Define the API dependencies."""

import logging
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import ValidationError

from app.core.auth.exceptions import (
    HTTPForbiddenException,
    HTTPUnauthorizedException,
    InactiveUserException,
)
from app.core.auth.utils import get_user_model
from app.core.config import settings
from app.core.log import set_log_context
from app.sep.config import sep_settings

logger = logging.getLogger(__name__)
User = get_user_model()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/oauth/token")

AuthToken = Annotated[str, Depends(oauth2_scheme)]

RefreshTokenCookie = Annotated[
    str | None, Cookie(alias=sep_settings.SESSION_REFRESH.COOKIE_NAME)
]

SERVICE_PRINCIPAL_ID = UUID("00000000-0000-4000-8000-000000000000")
_SERVICE_PRINCIPAL = User.build_service_principal(
    user_id=SERVICE_PRINCIPAL_ID,
    username="sep-service",
    first_name="SEP",
    last_name="Service",
)


def _build_service_principal(secret: str) -> User:
    """Return a per-request copy of the service principal with ``access_token`` set.

    ``access_token`` is a property-backed private attribute on ``BaseUser``;
    Pydantic v2's ``model_copy(update=...)`` silently drops non-field keys, so
    the value must be assigned via the property setter after the copy.

    :param secret: The unwrapped ``SEP_INTERNAL_TOKEN`` value.
    :type secret: str
    :return: A fresh copy of the singleton with ``access_token`` populated.
    :rtype: User
    """
    user = _SERVICE_PRINCIPAL.model_copy()
    user.access_token = secret
    return user


async def get_current_user(token: AuthToken) -> User:
    """Return the authenticated user from an OAuth2 token.

    When ``settings.SEP_INTERNAL_TOKEN`` is configured and the incoming Bearer
    token matches it (constant-time comparison), return a synthetic non-admin
    "service principal" user instead of contacting the OAuth provider. This
    allows SEP-internal service-to-service calls (e.g. scheduled inventory
    sync) to authenticate with a stable deployment-level secret rather than a
    short-lived personal access token.

    :param token: The OAuth2 token to authenticate the user.
    :type token: AuthToken
    :return: The authenticated user.
    :rtype: User
    :raises HTTPUnauthorizedException: If the token is invalid and authentication fails.
    :raises InactiveUserException: If authentication succeeds but the user is not
        active.
    """
    if (token_setting := settings.SEP_INTERNAL_TOKEN) is not None:
        secret = token_setting.get_secret_value()
        if secret and secrets.compare_digest(token, secret):
            set_log_context(user=_SERVICE_PRINCIPAL.username)
            return _build_service_principal(secret)
    try:
        user = await User.from_jwt(token)
    except ValidationError:
        logger.exception("Failed to authenticate user")
        raise HTTPUnauthorizedException from None
    if not user.is_active:
        raise InactiveUserException
    set_log_context(user=user.username)
    return user


IsAuthenticatedDep = Depends(get_current_user)
CurrentUser = Annotated[User, IsAuthenticatedDep]


async def get_current_admin(current_user: CurrentUser) -> User:
    """Return the authenticated admin from an OAuth2 token.

    :param current_user: The current logged-in user.
    :type current_user: CurrentUser
    :return: The authenticated admin user.
    :rtype: User
    :raises HTTPForbiddenException: If the user is not an admin.
    """
    if not current_user.is_admin:
        raise HTTPForbiddenException
    return current_user


IsAdminDep = Depends(get_current_admin)


def get_current_user_id(current_user: CurrentUser) -> str:
    """Get the current user's ID as a string.

    :param current_user: The current authenticated user.
    :type current_user: CurrentUser
    :return: The user's ID as a string.
    :rtype: str
    """
    return str(current_user.id)


CurrentUserID = Annotated[str, Depends(get_current_user_id)]
