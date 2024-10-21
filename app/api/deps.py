"""Define the API dependencies."""

import logging
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from pydantic import ValidationError

from app.api.exceptions import InactiveUserException
from app.core.auth.exceptions import HTTPForbiddenException, HTTPUnauthorizedException
from app.core.auth.utils import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()

# TODO: Consider what grant types to allow  # noqa: TD002, TD003
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/oauth/token")

AuthToken = Annotated[str, Depends(oauth2_scheme)]


async def get_current_user(token: AuthToken) -> User:
    """Return the authenticated user from an OAuth2 token.

    :param token: The OAuth2 token to authenticate the user.
    :type token: AuthToken
    :return: The authenticated user.
    :rtype: User
    :raises HTTPUnauthorizedException: If the token is invalid and authentication fails.
    :raises InactiveUserException: If authentication succeeds but the user is not
        active.
    """
    try:
        user = await User.from_jwt(token)
    except (InvalidTokenError, ValidationError):
        logger.exception("Failed to authenticate user")
        raise HTTPUnauthorizedException from None
    if not user.is_active:
        raise InactiveUserException
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
