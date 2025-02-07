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


# TODO: Prevent malicious account lockout  # noqa: TD002, TD003
@router.post("/token")
async def create_oauth_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> OAuthToken:
    """Generate an OAuth token for a user from their username and password.

    :param form_data: The form data containing username and password.
    :type form_data: OAuth2PasswordRequestForm
    :return: The OAuth token for the user.
    :rtype: OAuthToken
    :raises HTTPUnauthorizedException: If authentication fails due to incorrect
        credentials.
    :raises InactiveUserException: If the user is not active.
    """
    try:
        oauth_token = await User.get_oauth_token(
            username=form_data.username,
            password=form_data.password,
        )
    except ValidationError:
        logger.exception("Failed to authenticate user")
        raise HTTPUnauthorizedException("Incorrect username or password") from None

    user = await User.from_jwt(oauth_token.access_token)
    if not user.is_active:
        raise InactiveUserException

    return oauth_token


# TODO: refactor repeated code (refresh, token, maybe get_current_user)  # noqa: TD002, TD003
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
