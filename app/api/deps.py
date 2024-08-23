"""Define the API dependencies."""

import logging
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from pydantic import ValidationError

from app.api.exceptions import InactiveUserException
from app.core.auth.exceptions import HTTPUnauthorizedException
from app.core.auth.utils import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()

# TODO: Consider what grant types to allow
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/oauth/token")

AuthToken = Annotated[str, Depends(oauth2_scheme)]


async def get_current_user(token: AuthToken) -> User:
    """Return the authenticated user from an OAuth2 token.

    Parameters
    ----------
    token: AuthToken
        The OAuth2 token to authenticate the user.

    Returns
    -------
    User
        The authenticated user.

    Raises
    ------
    HTTPUnauthorizedException
        If the token is invalid and authentication fails.
    InactiveUserException
        If authentication succeeds but the user is not active.

    """
    try:
        user = await User.from_jwt(token)
    except (InvalidTokenError, ValidationError):
        logger.exception("Failed to authenticate user")
        raise HTTPUnauthorizedException from None
    if not user.is_active:
        raise InactiveUserException
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
